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

import argparse
import subprocess
import sys
import time
import os
import json
import glob

# Ensure we are always running from the project root (backend/)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT_DIR)

LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "simulation.log")


def _configure_docker_host():
    """Auto-configure DOCKER_HOST for Colima users if not already set.

    Colima's Docker socket is at ~/.colima/default/docker.sock. When a user
    runs `uv run start` without a DOCKER_HOST prefix this function discovers
    and exports the socket so every subsequent docker / docker-compose
    subprocess call works correctly — no manual prefix needed.
    """
    if "DOCKER_HOST" in os.environ:
        return  # Already set, respect it.
    default_socket = os.path.expanduser("~/.colima/default/docker.sock")
    if os.path.exists(default_socket):
        os.environ["DOCKER_HOST"] = f"unix://{default_socket}"
        print(f"🐳 Docker: Auto-configured Colima socket → {default_socket}")


# Configure Docker host at module level so ALL entry points benefit —
# both `python scripts/core/sim.py <cmd>` (via main()) and `uv run <cmd>`
# (console scripts that call functions directly, bypassing main()).
_configure_docker_host()


def _read_port_slot():
    """Read the current worktree port slot from .port-slot marker file.

    Returns 0 (default) if the marker file does not exist.
    """
    slot_path = os.path.join(ROOT_DIR, ".port-slot")
    try:
        with open(slot_path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _docker_compose_cmd():
    """Build the docker-compose command for the current slot.

    For non-zero slots, the override file is a STANDALONE compose file
    (not a merge override) to avoid Docker Compose's list-merging behavior
    with port bindings. It is used INSTEAD OF the base docker-compose.yml.
    """
    override_path = os.path.join(ROOT_DIR, "docker-compose.override.yml")
    slot = _read_port_slot()
    if slot > 0 and os.path.exists(override_path):
        # Standalone compose file for worktree slots
        return ["docker-compose", "-f", "docker-compose.override.yml"]
    return ["docker-compose", "-f", "docker-compose.yml"]


def _read_ports_from_env():
    """Read all *_PORT values from the local .env file.

    Returns a list of integer port numbers. Falls back to hardcoded defaults
    if .env cannot be read.
    """
    env_path = os.path.join(ROOT_DIR, ".env")
    ports = []
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.endswith("_PORT"):
                    try:
                        ports.append(int(value))
                    except ValueError:
                        pass
    except FileNotFoundError:
        # Fallback to default ports if .env doesn't exist
        ports = [8000, 8101, 8202, 8204, 8205, 8206, 8210, 8301, 8304, 8305]
    return ports


def _read_redis_port_from_env():
    """Read the Redis port from the local .env file.

    Returns the port number (default 8102 if not found).
    """
    env_path = os.path.join(ROOT_DIR, ".env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("REDIS_ADDR="):
                    _, addr = line.split("=", 1)
                    if ":" in addr:
                        return int(addr.rsplit(":", 1)[1])
    except (FileNotFoundError, ValueError):
        pass
    return 8102


def generate_catalog():
    """Scans all agents/**/agent.json and generates agents/catalog.json."""
    print("📋 Generating agent catalog...")
    catalog = {}
    # Use recursive glob for nested agents (npc/runner, etc.)
    agent_jsons = glob.glob("agents/**/agent.json", recursive=True)
    for path in agent_jsons:
        # Avoid the catalog itself if it was somehow named agent.json (unlikely)
        # But we want to avoid any templates or non-leaf directories.
        if "_template" in path or "npc/agent.json" == path:
            continue

        try:
            with open(path, "r") as f:
                card = json.load(f)

            # Key is the directory name
            key = os.path.basename(os.path.dirname(path))
            catalog[key] = card
            print(f"  ✅ Added {key} from {path}")
        except Exception as e:
            print(f"  ❌ Failed to parse {path}: {e}")

    catalog_path = "agents/catalog.json"
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"  ✨ Saved catalog to {catalog_path}")


def _read_env_file_value(key, default):
    """Read a single value from the local .env file, falling back to default."""
    env_path = os.path.join(ROOT_DIR, ".env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1]
    except FileNotFoundError:
        pass
    return default


def wait_for_infra():
    """Blocks until Redis and PubSub are truly accepting connections."""
    import socket

    # Read from .env file (not process env) so worktree slot ports are used
    redis_env = _read_env_file_value("REDIS_ADDR", "localhost:8102")
    pubsub_env = _read_env_file_value("PUBSUB_EMULATOR_HOST", "localhost:8103")

    # Parse addresses
    def parse_addr(env_val, default_port):
        if ":" in env_val:
            host, port = env_val.split(":")
            return (host, int(port))
        return (env_val, default_port)

    redis_addr = parse_addr(redis_env, 8102)
    pubsub_addr = parse_addr(pubsub_env, 8103)

    print("⏳ Waiting for infrastructure readiness...")
    for addr in [redis_addr, pubsub_addr]:
        start_time = time.time()
        timeout = 30
        connected = False
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(addr, timeout=1):
                    connected = True
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(1)

        if not connected:
            print(f"❌ Timeout waiting for {addr[0]}:{addr[1]}")
            sys.exit(1)
        print(f"  ✅ {addr[0]}:{addr[1]} is online.")


def preflight_infra():
    """Ensures Docker infrastructure is ready before starting simulation."""
    # DOCKER_HOST is already configured by _configure_docker_host() in main().
    # Just verify the daemon is reachable.
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
        print("🐳 Docker: Daemon is reachable and responsive.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: Docker daemon is not responding.")
        print("   If using Colima, run: colima start")
        print("   Otherwise ensure Docker Desktop is running.")
        sys.exit(1)

    # 1. Ensure images are present (pull from host side where DNS is reliable)
    images = ["redis:7-alpine", "gcr.io/google.com/cloudsdktool/cloud-sdk:latest"]
    print("📥 Checking/Pulling infrastructure images...")
    for img in images:
        res = subprocess.run(["docker", "image", "inspect", img], capture_output=True)
        if res.returncode != 0:
            print(f"  ☁️ Pulling {img} from host context...")
            subprocess.run(["docker", "pull", img])

    # 2. Start infrastructure independently to avoid honcho cascade
    print("🏗️ Starting infrastructure (Redis/PubSub)...")

    # Pre-remove stale containers to prevent name conflicts.
    # docker-compose --force-recreate fails if a container with the same name
    # exists from a different compose project (e.g., a previous worktree run
    # or manual docker-compose invocation). Silently removing them first
    # ensures a clean start.
    slot = _read_port_slot()
    stale_containers = [f"redis-slot-{slot}", f"pubsub-slot-{slot}"]
    for name in stale_containers:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    compose_cmd = _docker_compose_cmd()
    result = subprocess.run(
        compose_cmd + ["up", "-d", "--force-recreate", "--remove-orphans"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠️  docker-compose up failed: {result.stderr.strip()}")
        print("   Retrying after container cleanup...")
        for name in stale_containers:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(
            compose_cmd + ["up", "-d", "--remove-orphans"],
            check=True,
        )

    # 3. WAIT for it to be ready
    wait_for_infra()


def preflight_ui(force_install=False):
    """Ensures all frontend components are built before starting simulation."""
    projects = ["admin-dash", "tester", "agent-dash"]
    print("🎨 [UI] Checking and building frontend components...")

    for project in projects:
        project_path = os.path.join("web", project)
        if not os.path.exists(project_path):
            continue

        pkg_json = os.path.join(project_path, "package.json")
        if not os.path.exists(pkg_json):
            continue

        # 1. npm install if node_modules missing or forced
        node_modules = os.path.join(project_path, "node_modules")
        if not os.path.exists(node_modules) or force_install:
            print(f"  📦 Installing dependencies for {project}...")
            subprocess.run(["npm", "install"], cwd=project_path, check=True)

        # 2. Build if package.json has a build script and dist is missing
        import json

        with open(pkg_json, "r") as f:
            pkg_data = json.load(f)

        if "scripts" in pkg_data and "build" in pkg_data["scripts"]:
            dist_path = os.path.join(project_path, "dist")
            if not os.path.exists(dist_path) or force_install:
                print(f"  🏗️ Building {project}...")
                subprocess.run(["npm", "run", "build"], cwd=project_path, check=True)

    print("  ✅ All UI components are ready.")


def check_gcp_credentials():
    """Verifies that Google Cloud Application Default Credentials are valid."""
    print("☁️  Checking Google Cloud credentials...")
    try:
        # We try to print the access token; if it fails, ADC is likely invalid or expired
        subprocess.run(["gcloud", "auth", "application-default", "print-access-token"], capture_output=True, check=True)
        print("  ✅ GCP credentials are valid.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n❌ Error: Google Cloud Application Default Credentials (ADC) are missing or expired.")
        print("👉 Please run: gcloud auth application-default login")
        print("💡 If you are using gcert (Googlers), ensure you have a fresh ticket: gcert")
        sys.exit(1)


def init():
    """Initializes the repository and development environment."""
    print("🛠️ Initializing development environment...")

    # 0. Check credentials
    check_gcp_credentials()

    # 1. System Dependency Checks
    deps = ["docker", "npm", "go", "uv"]
    for dep in deps:
        if subprocess.run(["which", dep], capture_output=True).returncode != 0:
            print(f"❌ Error: {dep} is not installed or not in PATH.")
            sys.exit(1)
    print("  ✅ System dependencies found.")

    # 2. Environment Setup
    if not os.path.exists(".env"):
        print("  📝 Creating .env from .env.example...")
        import shutil

        shutil.copy(".env.example", ".env")
    else:
        print("  ✅ .env already exists.")

    # 3. Python Dependencies
    print("  🐍 Syncing Python dependencies...")
    subprocess.run(["uv", "sync"], check=True)

    # 4. UI Dependencies (Force install)
    preflight_ui(force_install=True)

    # 5. Go Dependencies
    print("  🐹 Tidying Go modules...")
    subprocess.run(["go", "mod", "tidy"], check=True)

    # 6. Protobuf Generation
    generate_protos()

    # 7. Infrastructure Preflight (Pull images)
    preflight_infra()

    print("\n✨ Repository initialization complete!")


def _run_honcho_with_logging(cmd, log_path=LOG_FILE):
    """Run a subprocess, teeing its output to both stdout and a logfile.

    Args:
        cmd: Command list to execute via Popen.
        log_path: Path to the logfile. Parent directory is created if needed.
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    with open(log_path, "w") as logfile:
        print(f"📝 Logging to {os.path.relpath(log_path, ROOT_DIR)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                sys.stdout.write(decoded)
                sys.stdout.flush()
                logfile.write(decoded)
                logfile.flush()
        except KeyboardInterrupt:
            print("\n🛑 Simulation stopped by user.")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            return

    rc = proc.wait()
    if rc != 0:
        print(f"❌ Process exited with code {rc}")
        sys.exit(rc)


def start(skip_tests=False, include_slow=False):
    """Starts the simulation using honcho."""
    # 0. Check credentials
    check_gcp_credentials()

    # 1. Infrastructure must be UP
    preflight_infra()

    # 2. UI Components must be BUILT
    preflight_ui(force_install=True)

    # 3. Generate Agent Catalog
    generate_catalog()

    if not skip_tests:
        test(include_slow=include_slow)
    slot = _read_port_slot()
    print(f"🚀 Starting simulation via honcho (slot {slot})...")

    _run_honcho_with_logging(["honcho", "start", "-f", "Procfile", "-e", ".env"])


def stop():
    """Stops the simulation processes and infrastructure.

    Port list is read dynamically from .env so this works correctly for any
    worktree slot. Infrastructure teardown is skipped for non-zero slots to
    avoid killing shared containers -- each slot manages its own containers
    via docker-compose override.
    """
    print("🛑 Stopping simulation...")

    slot = _read_port_slot()

    # 0. Purge Python bytecode caches (prevents stale .pyc from being served)
    print("🧹 Purging __pycache__ directories...")
    for dirpath, dirnames, _filenames in os.walk(os.path.join(ROOT_DIR, "agents")):
        if "__pycache__" in dirnames:
            cache_dir = os.path.join(dirpath, "__pycache__")
            import shutil

            shutil.rmtree(cache_dir, ignore_errors=True)
    print("  ✅ Bytecode caches cleared.")

    # 1a. Kill agent processes whose cwd is this worktree (catches rogues on wrong ports)
    my_root = ROOT_DIR
    print(f"Killing agent processes with cwd {my_root}...")
    try:
        ps_out = subprocess.check_output(["ps", "aux"], text=True)
        for line in ps_out.splitlines():
            if "agents/" not in line or "agent.py" not in line:
                continue
            parts = line.split()
            pid = parts[1]
            # Check if process cwd matches this worktree
            try:
                cwd = subprocess.check_output(
                    ["lsof", "-p", pid, "-Fn"],
                    text=True,
                    timeout=5,
                )
                if my_root in cwd:
                    print(f"  Killing agent process {pid} (cwd matches worktree)")
                    subprocess.run(["kill", "-9", pid], capture_output=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # If we can't check cwd and the full path is in the command, kill it
                if my_root in line:
                    print(f"  Killing agent process {pid} (path in command)")
                    subprocess.run(["kill", "-9", pid], capture_output=True)
    except subprocess.CalledProcessError:
        pass

    # 1b. Surgical Port Cleanup (catches non-agent processes on our ports)
    ports = _read_ports_from_env()
    print(f"Cleaning up simulation ports (slot {slot}): {ports}")
    for port in ports:
        try:
            cmd = f"lsof -ti :{port} -sTCP:LISTEN"
            pids = subprocess.check_output(cmd, shell=True).decode().split()
            for pid in pids:
                print(f"  Killing process {pid} on port {port}...")
                subprocess.run(["kill", "-9", pid], capture_output=True)
        except subprocess.CalledProcessError:
            pass

    # 2. Flush Redis (sessions + pub/sub backlog)
    flush_redis()

    print("Stopping infrastructure (Redis/PubSub)...")
    compose_cmd = _docker_compose_cmd()
    subprocess.run(compose_cmd + ["down"], capture_output=True)
    # Force-remove containers in case docker-compose down left orphans
    # (can happen when a container was created by a different compose project)
    for name in [f"redis-slot-{slot}", f"pubsub-slot-{slot}"]:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    print("✅ Simulation stopped and infrastructure cleared.")


def flush_redis():
    """Flush all Redis data (sessions, pub/sub backlog, spawn queues).

    Tries redis-cli first, falls back to Python redis client.
    """
    redis_port = _read_redis_port_from_env()
    print(f"🗑️  Flushing Redis on port {redis_port}...")

    # Try redis-cli first (fastest)
    result = subprocess.run(
        f"redis-cli -p {redis_port} flushall",
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and "OK" in result.stdout:
        print(f"  ✅ Redis flushed via redis-cli (port {redis_port})")
        return

    # Fallback: use Python redis client
    try:
        import redis

        r = redis.Redis(host="127.0.0.1", port=redis_port)
        r.flushall()
        r.close()
        print(f"  ✅ Redis flushed via Python client (port {redis_port})")
    except Exception as e:
        print(f"  ⚠️  Could not flush Redis on port {redis_port}: {e}")
        print("     (Redis may not be running — this is OK if you're stopping.)")


def restart(skip_tests=False, include_slow=False):
    """Restarts the simulation."""
    stop()
    time.sleep(2)
    start(skip_tests=skip_tests, include_slow=include_slow)


def generate_protos():
    """Generates Protobuf bindings if missing or needed."""
    proto_script = "scripts/core/generate_proto.sh"
    if not os.path.exists(proto_script):
        print(f"⚠️  Warning: {proto_script} not found. Skipping proto generation.")
        return

    print("🔨 Ensuring Protobuf bindings are up to date...")
    try:
        subprocess.run(["bash", proto_script], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: Protobuf generation failed: {e}")
        # We don't exit here because older bindings might still work,
        # but Go tests will likely fail later if they are missing.


def test(include_slow=False):
    """Runs all unit tests (Python and Go)."""
    # 0. Check credentials
    check_gcp_credentials()

    # Ensure catalog is generated before testing (Go tests need it)
    generate_catalog()
    # Ensure protos are generated before testing
    generate_protos()

    print("🧪 Running all unit tests...")

    print("\n🐍 [Python] Testing agents and utils...")
    pytest_cmd = [".venv/bin/pytest", "agents"]
    if not include_slow:
        pytest_cmd.extend(["-m", "not slow"])
    py_res = subprocess.run(pytest_cmd, check=False)

    print("\n🐹 [Go] Testing internal packages and gateway...")
    go_res = subprocess.run(["go", "test", "./..."], check=False)

    if py_res.returncode != 0 or go_res.returncode != 0:
        print("\n❌ Unit testing failed.")
        sys.exit(1)
    print("\n✅ All unit tests passed.")


def main():
    # No-op if already configured at module level, but kept as a safety net
    # for direct `python scripts/core/sim.py` invocations.
    _configure_docker_host()

    parser = argparse.ArgumentParser(description="Simulation Lifecycle Manager")
    parser.add_argument(
        "command",
        choices=[
            "init",
            "start",
            "stop",
            "restart",
            "flush",
            "test",
        ],
        help="Command to execute",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip pre-launch tests")
    parser.add_argument("--include-slow", action="store_true", help="Include slow-marked tests")
    args = parser.parse_args()

    if args.command == "init":
        init()
    elif args.command == "start":
        start(skip_tests=args.skip_tests, include_slow=args.include_slow)
    elif args.command == "stop":
        stop()
    elif args.command == "restart":
        restart(skip_tests=args.skip_tests, include_slow=args.include_slow)
    elif args.command == "flush":
        flush_redis()
    elif args.command == "test":
        test(include_slow=args.include_slow)


if __name__ == "__main__":
    main()
