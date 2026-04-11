# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate worktree-specific .env and docker-compose.override.yml files.

Each worktree slot (0-3) gets a port offset of slot * 1000 applied to all
service ports, addresses, and URLs. Infrastructure ports (Redis, PubSub)
are also offset so each worktree gets isolated containers.

Usage:
    python scripts/core/gen_worktree_env.py --slot 1
    make worktree-env SLOT=1
"""

import argparse
import os
import re
import subprocess
import sys

MAX_SLOT = 3
OFFSET_MULTIPLIER = 1000

# Variables whose values contain ports that need offsetting.
# Categorized by how to parse them.
PORT_VARS = {
    "PORT",
    "ADMIN_PORT",
    "GATEWAY_PORT",
    "DASH_PORT",
    "TESTER_PORT",
    "SIMULATOR_PORT",
    "PLANNER_PORT",
    "PLANNER_WITH_EVAL_PORT",
    "SIMULATOR_WITH_FAILURE_PORT",
    "RUNNER_PORT",
    "PLANNER_WITH_MEMORY_PORT",
    "RUNNER_AUTOPILOT_PORT",
    "FRONTEND_APP_PORT",
    "FRONTEND_BFF_PORT",
}

# Pattern: host:port
ADDR_VARS = {
    "GATEWAY_ADDR",
    "SIMULATOR_ADDR",
    "PLANNER_ADDR",
    "PLANNER_WITH_EVAL_ADDR",
    "PLANNER_WITH_MEMORY_ADDR",
    "RUNNER_ADDR",
    "RUNNER_AUTOPILOT_ADDR",
    "REDIS_ADDR",
    "PUBSUB_EMULATOR_HOST",
}

# Pattern: scheme://host:port or scheme://host:port/path
URL_VARS = {
    "SIMULATOR_URL",
    "PLANNER_URL",
    "PLANNER_WITH_EVAL_URL",
    "SIMULATOR_WITH_FAILURE_URL",
    "PLANNER_WITH_MEMORY_URL",
    "RUNNER_URL",
    "RUNNER_AUTOPILOT_URL",
    "GATEWAY_URL",
    "TESTER_URL",
    "DASH_URL",
    "ADMIN_URL",
    "FRONTEND_APP_URL",
    "FRONTEND_BFF_URL",
    "VITE_GATEWAY_URL",
    "VITE_GATEWAY_ADDR",
}

# Comma-separated list of URLs
MULTI_URL_VARS = {
    "AGENT_URLS",
}


def apply_offset(port: int, slot: int) -> int:
    """Apply port offset based on slot number.

    Args:
        port: The base port number.
        slot: The worktree slot (0-3).

    Returns:
        The offset port number.

    Raises:
        ValueError: If slot is out of range.
    """
    if slot < 0 or slot > MAX_SLOT:
        raise ValueError(f"Slot must be between 0 and {MAX_SLOT}, got {slot}")
    return port + (slot * OFFSET_MULTIPLIER)


def _offset_port_in_addr(value: str, slot: int) -> str:
    """Offset the port in a host:port string."""
    if ":" not in value:
        return value
    host, port_str = value.rsplit(":", 1)
    try:
        port = int(port_str)
        return f"{host}:{apply_offset(port, slot)}"
    except ValueError:
        return value


def _offset_port_in_url(value: str, slot: int) -> str:
    """Offset the port in a URL like http://host:port/path."""
    # Match scheme://host:port with optional /path
    pattern = r"^((?:https?|wss?|grpc)://[^:]+:)(\d+)(.*)?$"
    match = re.match(pattern, value)
    if match:
        prefix = match.group(1)
        port = int(match.group(2))
        suffix = match.group(3) or ""
        return f"{prefix}{apply_offset(port, slot)}{suffix}"
    return value


def transform_env_line(line: str, slot: int) -> str:
    """Transform a single .env line by applying the port offset.

    Args:
        line: A single line from the .env file.
        slot: The worktree slot (0-3).

    Returns:
        The transformed line.
    """
    # Skip comments and empty lines
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line

    # Parse KEY=VALUE
    if "=" not in stripped:
        return line

    key, value = stripped.split("=", 1)

    if slot == 0:
        return line

    if key in PORT_VARS:
        try:
            port = int(value)
            return f"{key}={apply_offset(port, slot)}"
        except ValueError:
            return line

    if key in ADDR_VARS:
        return f"{key}={_offset_port_in_addr(value, slot)}"

    if key in URL_VARS:
        return f"{key}={_offset_port_in_url(value, slot)}"

    if key in MULTI_URL_VARS:
        urls = value.split(",")
        offset_urls = [_offset_port_in_url(u.strip(), slot) for u in urls]
        return f"{key}={','.join(offset_urls)}"

    return line


def _fetch_alloydb_password(
    project: str = "n26-devkey-simulation-dev",
    secret_name: str = "am-db-password",
) -> str | None:
    """Fetch the AlloyDB postgres password from GCP Secret Manager.

    Returns the password string, or None if the fetch fails (e.g. no gcloud
    auth, no access, or running offline).
    """
    try:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={secret_name}",
                f"--project={project}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        password = result.stdout.strip()
        if password:
            return password
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"  ⚠️  Could not fetch AlloyDB password from Secret Manager: {exc}", file=sys.stderr)
        print("     Falling back to placeholder. Update ALLOYDB_PASSWORD in .env manually.", file=sys.stderr)
    return None


def generate_env(
    template_path: str,
    output_path: str,
    slot: int,
    slot_marker_path: str | None = None,
    use_alloydb: bool = False,
    alloydb_password: str | None = None,
) -> None:
    """Generate a .env file with offset ports from a template.

    Args:
        template_path: Path to .env.example.
        output_path: Path to write the generated .env.
        slot: The worktree slot (0-3).
        slot_marker_path: Optional path to write the .port-slot marker file.
        use_alloydb: Whether to configure the DB for AlloyDB proxy instead of local Postgres.
        alloydb_password: The explicit password to insert (auto-fetched from Secret Manager if omitted).
    """
    with open(template_path) as f:
        lines = f.readlines()

    transformed = []
    for line in lines:
        # Preserve line endings
        stripped = line.rstrip("\n")

        if use_alloydb and "=" in stripped and not stripped.startswith("#"):
            key, val = stripped.split("=", 1)
            # Use explicit provided password, or auto-fetch from Secret Manager.
            if alloydb_password:
                db_pass = alloydb_password
            else:
                # Lazy fetch — only call Secret Manager once.
                if not hasattr(generate_env, "_cached_password"):
                    fetched = _fetch_alloydb_password()
                    generate_env._cached_password = fetched if fetched else "localdev"
                db_pass = generate_env._cached_password

            if key == "USE_ALLOYDB":
                stripped = "USE_ALLOYDB=true"
            elif key == "ALLOYDB_SCHEMA":
                stripped = "ALLOYDB_SCHEMA=local_dev"
            elif key == "ALLOYDB_PASSWORD":
                stripped = f"ALLOYDB_PASSWORD={db_pass}"
            elif key == "ALLOYDB_PORT":
                stripped = "ALLOYDB_PORT=5433"
            elif key == "ALLOYDB_HOST":
                stripped = "ALLOYDB_HOST=127.0.0.1"

        transformed.append(transform_env_line(stripped, slot))

    with open(output_path, "w") as f:
        f.write("\n".join(transformed))
        if transformed:
            f.write("\n")

    if slot_marker_path is not None:
        with open(slot_marker_path, "w") as f:
            f.write(f"{slot}\n")


def generate_docker_compose_override(override_path: str, slot: int) -> None:
    """Generate a docker-compose.override.yml for the given slot.

    For slot 0, no override file is created (uses default ports).
    For slots 1-3, creates a **standalone** compose file (not a merge override)
    with the full service definitions using offset ports and unique container
    names. This avoids Docker Compose's list-merging behavior which would
    append offset ports to the base ports instead of replacing them.

    Args:
        override_path: Path to write docker-compose.override.yml.
        slot: The worktree slot (0-3).
    """
    if slot == 0:
        # Slot 0 uses default ports, no override needed
        return

    redis_port = apply_offset(8102, slot)
    pubsub_port = apply_offset(8103, slot)

    content = f"""\
# Auto-generated by gen_worktree_env.py for slot {slot}
# DO NOT EDIT -- regenerate with: make worktree-env SLOT={slot}
#
# This is a STANDALONE compose file (not a merge override) because
# Docker Compose merges list values (ports) by appending, which would
# cause both old and new port bindings to exist simultaneously.
# Use with: docker-compose -f docker-compose.override.yml up -d
services:
  redis:
    image: redis:7-alpine
    container_name: redis-slot-{slot}
    command: redis-server --maxclients 256 --tcp-backlog 128 --save "" --stop-writes-on-bgsave-error no
    ulimits:
      nofile:
        soft: 1024
        hard: 1024
    ports:
      - "{redis_port}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
  pubsub:
    image: gcr.io/google.com/cloudsdktool/cloud-sdk:latest
    container_name: pubsub-slot-{slot}
    command: gcloud beta emulators pubsub start --host-port=0.0.0.0:8085
    ports:
      - "{pubsub_port}:8085"
    environment:
      - PUBSUB_PROJECT_ID=test-project
"""

    with open(override_path, "w") as f:
        f.write(content)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate worktree-specific .env and docker-compose override")
    parser.add_argument(
        "--slot",
        type=int,
        required=True,
        help=f"Worktree slot number (0-{MAX_SLOT})",
    )
    parser.add_argument(
        "--template",
        default=".env.example",
        help="Path to .env template (default: .env.example)",
    )
    parser.add_argument(
        "--output",
        default=".env",
        help="Path to write generated .env (default: .env)",
    )
    parser.add_argument(
        "--use-alloydb",
        action="store_true",
        help="Configure .env for AlloyDB Auth Proxy instead of local Postgres",
    )
    parser.add_argument(
        "--alloydb-password",
        default=os.environ.get("ALLOYDB_PASSWORD"),
        help="Password for AlloyDB proxy (default: from ALLOYDB_PASSWORD env var)",
    )

    args = parser.parse_args()

    if args.slot < 0 or args.slot > MAX_SLOT:
        print(f"Error: Slot must be between 0 and {MAX_SLOT}", file=sys.stderr)
        sys.exit(1)

    # Resolve paths relative to project root
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    template = os.path.join(root, args.template)
    output = os.path.join(root, args.output)
    slot_marker = os.path.join(root, ".port-slot")
    override = os.path.join(root, "docker-compose.override.yml")

    if not os.path.exists(template):
        print(f"Error: Template file not found: {template}", file=sys.stderr)
        sys.exit(1)

    generate_env(template, output, args.slot, slot_marker, args.use_alloydb, args.alloydb_password)
    generate_docker_compose_override(override, args.slot)

    offset = args.slot * OFFSET_MULTIPLIER
    if args.slot == 0:
        print(f"Generated {output} with default ports (slot 0, no offset)")
    else:
        print(f"Generated {output} with +{offset} port offset (slot {args.slot})")
        print(f"Generated {override} with infrastructure ports")
    print(f"Slot marker written to {slot_marker}")


if __name__ == "__main__":
    main()
