#!/usr/bin/env python3
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

"""Per-agent Vertex AI Agent Engine deployment for the OSS one-shot deploy.

Entry point used by cloudbuild-bootstrap.yaml:

    python scripts/deploy/deploy.py --only <agent> --print-url

Cloud Build runs this in parallel (one step per agent) and captures the
printed A2A resource URL via ``| tail -1`` into /workspace/ae_urls/<agent>.url
for the gateway's AGENT_URLS env var.

Cloud Run services, IAM, image builds, and DB schema are owned by Terraform
and other Cloud Build steps -- not by this script.
"""

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import google.auth
import requests

# --- Terraform output cache ---

_terraform_outputs_cache: dict | None = None

# Cloud Build path: the read-tf-outputs step writes terraform output -json
# to this file, so the python:3.13-slim AE deploy steps (which do NOT have
# a terraform binary) can still load infrastructure values without shelling
# out. Module-level for monkeypatchability in tests.
_TF_OUTPUTS_FILE = "/workspace/tf_outputs.json"


def _read_terraform_outputs() -> dict:
    """Read infrastructure values from Terraform outputs.

    Resolution order:
      1. /workspace/tf_outputs.json (Cloud Build path; the slim python image
         has no terraform binary -- without this, AE deploys silently fall
         back to empty env vars and Vertex rejects them).
      2. ``terraform -chdir=infra output -json`` (local dev with terraform on PATH).
      3. Environment variables (last-resort fallback).
    """
    global _terraform_outputs_cache
    if _terraform_outputs_cache is not None:
        return _terraform_outputs_cache

    raw: dict | None = None

    # 1. Cloud Build path: read the JSON file already produced by terraform.
    if os.path.exists(_TF_OUTPUTS_FILE):
        try:
            with open(_TF_OUTPUTS_FILE) as f:
                raw = json.load(f)
            print(f"  Loaded Terraform outputs from {_TF_OUTPUTS_FILE}")
        except (OSError, json.JSONDecodeError) as e:
            print(f"  {_TF_OUTPUTS_FILE} present but unreadable ({e}); falling back")

    # 2. Local dev path: shell out to terraform.
    if raw is None:
        try:
            result = subprocess.run(
                ["terraform", "-chdir=infra", "output", "-json"],
                capture_output=True,
                text=True,
                check=True,
            )
            raw = json.loads(result.stdout)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            print(f"  Terraform outputs unavailable ({e}), falling back to env vars")
            raw = {}

    # Terraform wraps each output as {"value": ..., "type": ...}; unwrap.
    outputs = {k: v.get("value", v) if isinstance(v, dict) else v for k, v in raw.items()}

    _terraform_outputs_cache = {
        "project_id": outputs.get("project_id", os.getenv("PROJECT_ID", "")),
        "region": outputs.get("region", os.getenv("REGION", "us-central1")),
        "redis_host": outputs.get("redis_host", os.getenv("REDIS_HOST", "")),
        "redis_port": outputs.get("redis_port", os.getenv("REDIS_PORT", "6379")),
        "pubsub_topic": outputs.get("pubsub_topic", os.getenv("PUBSUB_TOPIC_ID", "agent-telemetry")),
        "orchestration_topic": outputs.get(
            "orchestration_topic",
            os.getenv("ORCHESTRATION_TOPIC_ID", "specialist-orchestration"),
        ),
        "agent_engine_sa_email": outputs.get("agent_engine_sa_email", os.getenv("AGENT_ENGINE_SA_EMAIL", "")),
        "psc_network_attachment": outputs.get("psc_network_attachment", os.getenv("PSC_NETWORK_ATTACHMENT", "")),
        "staging_bucket": outputs.get("staging_bucket", os.getenv("STAGING_BUCKET", "")),
        # Database connection info, consumed by deploy_agent_engine to wire
        # ALLOYDB_* env vars on the planner_with_memory AE engine. The
        # ALLOYDB_ prefix is misleading -- in OSS this resolves to the
        # Cloud SQL private IP (enable_alloydb=false by default) and the
        # agent code's USE_ALLOYDB=false switch flips it to the Cloud SQL
        # + Vertex AI embedding code path.
        "database_ip": outputs.get("database_ip", os.getenv("DATABASE_IP", "")),
        "database_type": outputs.get("database_type", os.getenv("DATABASE_TYPE", "cloud-sql")),
        "database_password_secret_id": outputs.get(
            "database_password_secret_id",
            os.getenv("DATABASE_PASSWORD_SECRET_ID", ""),
        ),
        "database_name": outputs.get("database_name", os.getenv("DATABASE_NAME", "")),
    }
    return _terraform_outputs_cache


# --- Gateway URL discovery (best-effort) ---


def _get_gateway_url(project_id: str, region: str) -> str | None:
    """Discover the gateway's Cloud Run URL via gcloud, if available.

    Returns None when gcloud is unavailable (e.g. inside the slim
    python:3.13-slim Cloud Build step) or when the gateway service has
    not yet been deployed. Callers should treat None as "leave empty".
    """
    try:
        result = subprocess.run(
            [
                "gcloud",
                "run",
                "services",
                "describe",
                "gateway",
                f"--project={project_id}",
                f"--region={region}",
                "--format=value(status.url)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
        return url if url else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# --- Service definitions: Agent Engine agents only ---

# Smallest usable AE config for OSS cost-efficiency.
# 2Gi/1CPU is enough for the agent ADK runtime to load; the hot path is
# waiting on Gemini API responses, not local compute. min_instances and
# max_instances are intentionally not set so AE uses its defaults
# (scale-to-zero between simulations).
SERVICES = {
    "simulator": {
        "type": "reasoning-engine",
        "path": "agents/simulator",
        "module": "agents.simulator.agent",
        "attr": "simulator_a2a_agent",
        "resource_limits": {"memory": "2Gi", "cpu": "1"},
    },
    "planner": {
        "type": "reasoning-engine",
        "path": "agents/planner",
        "module": "agents.planner.agent",
        "attr": "planner_a2a_agent",
        "resource_limits": {"memory": "2Gi", "cpu": "1"},
    },
    "planner_with_eval": {
        "type": "reasoning-engine",
        "path": "agents/planner_with_eval",
        "module": "agents.planner_with_eval.agent",
        "attr": "planner_a2a_agent",
        "extra_packages": ["agents/planner"],
        "resource_limits": {"memory": "2Gi", "cpu": "1"},
    },
    "simulator_with_failure": {
        "type": "reasoning-engine",
        "path": "agents/simulator_with_failure",
        "module": "agents.simulator_with_failure.agent",
        "attr": "simulator_with_failure_a2a_agent",
        "extra_packages": ["agents/simulator"],
        "resource_limits": {"memory": "2Gi", "cpu": "1"},
    },
    "planner_with_memory": {
        "type": "reasoning-engine",
        "path": "agents/planner_with_memory",
        "module": "agents.planner_with_memory.agent",
        "attr": "planner_a2a_agent",
        "extra_packages": ["agents/planner", "agents/planner_with_eval"],
        "resource_limits": {"memory": "2Gi", "cpu": "1"},
    },
}


# --- Agent Engine helpers ---


def _extract_resource_name(url: str) -> str | None:
    """Extract the resource name from an Agent Engine A2A endpoint URL.

    Given ``https://.../v1beta1/projects/.../reasoningEngines/ID``
    returns ``projects/.../reasoningEngines/ID``.
    """
    prefix = "/v1beta1/"
    idx = url.find(prefix)
    if idx == -1:
        return None
    resource = url[idx + len(prefix) :]
    return resource if resource else None


def _compute_staging_fingerprint(staging_dir: str) -> str:
    """Compute a SHA-256 fingerprint of all staged source files."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(staging_dir):
        dirs.sort()
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, staging_dir)
            h.update(relpath.encode())
            with open(fpath, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def _get_card_url(resource_name: str, location: str) -> str:
    """Build the A2A card URL for an Agent Engine resource."""
    api_endpoint = f"https://{location}-aiplatform.googleapis.com"
    return f"{api_endpoint}/v1beta1/{resource_name}/a2a/v1/card"


def _build_resource_url(resource_name: str, location: str) -> str:
    """Build the A2A resource URL for an Agent Engine deployment.

    This is the URL the cloudbuild-bootstrap.yaml orchestrator captures via
    `... | tail -1` to populate AGENT_URLS for the gateway. Must be a clean
    string with no surrounding whitespace or extra tokens.
    """
    api_endpoint = f"https://{location}-aiplatform.googleapis.com"
    return f"{api_endpoint}/v1beta1/{resource_name}"


def _fetch_current_card_version(resource_name: str, location: str) -> str | None:
    """Fetch the current card version from a deployed Agent Engine."""
    import google.auth.transport.requests as google_requests

    card_url = _get_card_url(resource_name, location)
    try:
        creds, _ = google.auth.default()
        auth_req = google_requests.Request()
        creds.refresh(auth_req)
        resp = requests.get(
            card_url,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("version")
    except Exception:
        pass
    return None


def _verify_deployed_agent(
    service_name: str,
    resource_name: str,
    location: str,
    *,
    expected_fingerprint: str | None = None,
    previous_fingerprint: str | None = None,
    timeout: int = 180,
    interval: int = 15,
) -> bool | None:
    """Poll the deployed agent's card and verify name and fingerprint match.

    Returns True on match, False on mismatch, None on timeout.
    """
    import google.auth.transport.requests as google_requests

    card_url = _get_card_url(resource_name, location)

    print(f"\n  Verifying deployment (polling {card_url})...")
    if expected_fingerprint:
        print(f"   Expected fingerprint: {expected_fingerprint}")
        if previous_fingerprint:
            if previous_fingerprint == expected_fingerprint:
                print(f"   Fingerprint unchanged from previous deploy")
            else:
                print(f"   Previous fingerprint: {previous_fingerprint}")

    creds, _ = google.auth.default()
    auth_req = google_requests.Request()

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            creds.refresh(auth_req)
            resp = requests.get(
                card_url,
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                card = resp.json()
                card_name = card.get("name", "<missing>")
                if card_name != service_name:
                    print(f"   Card name mismatch! Expected '{service_name}', got '{card_name}'")
                    return False

                if expected_fingerprint:
                    card_version = card.get("version", "<missing>")
                    if card_version == expected_fingerprint:
                        print(f"   Card name matches: '{card_name}'")
                        print(f"   Build fingerprint verified: {card_version}")
                        return True
                    print(f"   Name OK but fingerprint stale ({card_version}), retrying in {interval}s...")
                else:
                    print(f"   Card name matches: '{card_name}'")
                    return True
            else:
                print(f"   Not ready yet (HTTP {resp.status_code}), retrying in {interval}s...")
        except Exception as e:
            print(f"   Not reachable yet ({e}), retrying in {interval}s...")
        time.sleep(interval)

    print(f"   Timed out after {timeout}s. Verify manually: {card_url}")
    return None


# Vertex AI SDK seams kept behind module-level helpers for test patchability.
# Location is implicit from vertexai.init() in deploy_agent_engine; the SDK
# doesn't accept a location filter on agent_engines.list().


def _is_not_found(exc: Exception) -> bool:
    """True if exc is a 'resource genuinely does not exist' signal.

    Discriminates a legitimate first-deploy NotFound (safe to fall through)
    from auth/quota/network errors (must propagate). Uses a class-name
    fallback so tests can use a stand-in NotFound without depending on
    google.api_core.
    """
    try:
        from google.api_core import exceptions as gae

        if isinstance(exc, gae.NotFound):
            return True
    except ImportError:
        pass
    return type(exc).__name__ == "NotFound"


def _lookup_engine_by_resource_name(resource_name: str) -> bool:
    """True iff an Agent Engine with this resource_name still exists.

    Returns False on NotFound (engine deleted; fall through to discovery).
    Re-raises permission/quota/network errors so the deploy fails loudly.
    """
    try:
        from vertexai import agent_engines

        agent_engines.get(resource_name)
        return True
    except Exception as e:
        if _is_not_found(e):
            print(f"   Engine {resource_name} not found; falling back to discovery")
            return False
        raise


def _list_reasoning_engines() -> list:
    """List Agent Engines in the configured project/location.

    Returns [] only on genuine NotFound (project has no AEs yet). Re-raises
    permission/quota/network errors -- silently returning [] would orphan AEs
    on every Cloud Build re-run.
    """
    try:
        from vertexai import agent_engines

        return list(agent_engines.list())
    except Exception as e:
        if _is_not_found(e):
            return []
        raise


def _find_engine_by_display_name(service_name: str) -> str | None:
    """Discover an existing Agent Engine by displayName, returning its
    resource_name (or None).

    OSS deploys have no {SERVICE}_INTERNAL_URL env source, so without this
    fallback every Cloud Build re-run would orphan a fresh AE. When multiple
    engines share the display_name, picks the most-recently-updated one;
    engines missing update_time are treated as older than any real candidate.
    """
    from datetime import datetime, timezone

    engines = _list_reasoning_engines()
    matching = [e for e in engines if getattr(e, "display_name", None) == service_name]
    if not matching:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    matching.sort(key=lambda e: getattr(e, "update_time", None) or epoch, reverse=True)
    return matching[0].resource_name


def _determine_deploy_mode(
    service_name: str,
    *,
    force_create: bool = False,
) -> tuple[str, str | None]:
    """Resolve to ("update", resource_name) or ("create", None).

    Order: force_create -> {SERVICE}_INTERNAL_URL (dev/prod fast path) ->
    discovery by display_name (OSS path; without this, every Cloud Build
    re-run orphans a fresh AE) -> create.
    """
    if force_create:
        return "create", None

    env_key = f"{service_name.upper()}_INTERNAL_URL"
    existing_url = os.environ.get(env_key)
    if existing_url:
        resource_name = _extract_resource_name(existing_url)
        if resource_name and _lookup_engine_by_resource_name(resource_name):
            print(f"   Found existing engine via {env_key}: {resource_name}")
            return "update", resource_name
        if not resource_name:
            print(f"   {env_key} is not an AE URL, falling back to discovery")
        else:
            print(f"   {env_key}-pointed engine is gone, falling back to discovery")

    discovered = _find_engine_by_display_name(service_name)
    if discovered:
        print(f"   Found existing engine via display_name '{service_name}': {discovered}")
        return "update", discovered

    return "create", None


# --- Agent Engine staging helpers ---

_STAGING_IGNORE_DIRS = {
    "__pycache__",
    ".adk",
    "tests",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
}
_STAGING_IGNORE_SUFFIXES = (".pyc", ".pb.go", ".proto")
_STAGING_IGNORE_NAMES = {"README.md"}
_STAGING_IGNORE_PREFIXES = ("test_",)


def _staging_ignore(directory: str, entries: list[str]) -> set[str]:
    ignored = set()
    for entry in entries:
        full_path = os.path.join(directory, entry)
        if os.path.isdir(full_path) and entry in _STAGING_IGNORE_DIRS:
            ignored.add(entry)
            continue
        if os.path.isfile(full_path):
            if entry.endswith(_STAGING_IGNORE_SUFFIXES):
                ignored.add(entry)
            elif entry in _STAGING_IGNORE_NAMES:
                ignored.add(entry)
            elif entry.startswith(_STAGING_IGNORE_PREFIXES):
                ignored.add(entry)
            elif entry.endswith("_test.py"):
                ignored.add(entry)
    return ignored


def _stage_extra_packages(
    extra_packages: list[str],
) -> tuple[str, list[str]]:
    """Stage extra_packages into a clean temp directory for Agent Engine.

    Preserves the original directory hierarchy (e.g. ``agents/simulator``
    stays as ``agents/simulator``). Caller must clean up the returned
    temp directory.

    Returns (temp_dir_path, staged_package_paths).
    """
    staging_dir = tempfile.mkdtemp(prefix="ae-staging-")
    for pkg_path in extra_packages:
        dest = os.path.join(staging_dir, pkg_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isfile(pkg_path):
            shutil.copy2(pkg_path, dest)
        elif os.path.isdir(pkg_path):
            shutil.copytree(pkg_path, dest, ignore=_staging_ignore)
        else:
            print(f"   Skipping non-existent path: {pkg_path}")
            continue
    staged_paths = sorted(os.listdir(staging_dir))
    return staging_dir, staged_paths


def _read_requirements():
    """Read project dependencies from pyproject.toml for Agent Engine."""
    try:
        import tomllib

        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("dependencies", [])
    except Exception as e:
        print(f"   Could not read pyproject.toml: {e}")
        return []


# Cloudpickle bytes embed class definitions and state-dict shapes from
# the build venv. If the Agent Engine runtime resolves any of those
# class-providing packages to a DIFFERENT version (e.g. ``a2a-sdk>=0.3.26``
# resolves to ``1.0.0`` at runtime while the build had ``0.3.26`` from
# uv.lock), the runtime's class has different ``__setstate__`` semantics
# or attribute layout and ``cloudpickle.loads()`` blows up partway
# through reconstruction.
#
# Observed in the wild on a fresh OSS Agent Engine create:
# ``KeyError: 'serialized'`` from ``protobuf.Message.__setstate__`` --
# the underlying state dict came from a transitive Pydantic model in a
# newer ``a2a-sdk`` whose pickle reduce path the older build's protobuf
# didn't understand.
#
# Defensive fix: pin EVERY top-level requirement to the exact version
# installed in the build venv. This forces the AE runtime container to
# match build byte-for-byte for the dependency closure we declared.
def _pin_all_requirements(requirements):
    """Rewrite every requirement to ``pkg[extras]==<resolved version>`` from the venv."""
    import importlib.metadata
    import re

    def _pkg_name(req):
        # Strip extras and constraints to get the bare distribution name.
        return re.split(r"[<>=!~\[ ]", req, maxsplit=1)[0].strip().lower()

    def _pkg_extras(req):
        # Preserve ``[extras]`` since they affect what pip installs.
        m = re.search(r"\[[^\]]+\]", req)
        return m.group(0) if m else ""

    pinned = []
    for req in requirements:
        name = _pkg_name(req)
        extras = _pkg_extras(req)
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            # Not installed in the build venv -- keep the original constraint.
            pinned.append(req)
            continue
        pinned.append(f"{name}{extras}=={version}")
    return pinned


# --- Deploy: Agent Engine ---


def deploy_agent_engine(service_name: str, cfg: dict, *, tf: dict, force_create: bool = False) -> str:
    """Create or update an agent on Vertex AI Agent Engine.

    Returns the A2A resource URL; main() prints it as the final stdout line
    so cloudbuild-bootstrap.yaml can capture it with ``... | tail -1``.
    """
    import vertexai

    module_path = cfg.get("module")
    attr_name = cfg.get("attr")
    agent_path = cfg.get("path")
    if not module_path or not attr_name or not agent_path:
        print(f"  {service_name}: missing 'module', 'attr', or 'path' in SERVICES config")
        sys.exit(1)

    project_id = tf["project_id"]
    ae_location = os.getenv("AGENT_ENGINE_LOCATION", tf["region"])
    staging_bucket = tf.get("staging_bucket") or os.getenv("STAGING_BUCKET", f"gs://{project_id}-staging")

    print(
        f"  Deploying {service_name} to Agent Engine\n"
        f"   Project:  {project_id}\n"
        f"   Location: {ae_location}\n"
        f"   Staging:  {staging_bucket}"
    )

    # Override GOOGLE_CLOUD_LOCATION for Agent Engine SDK
    # (requires real region, not ``global``).
    saved_location = os.environ.get("GOOGLE_CLOUD_LOCATION")
    os.environ["GOOGLE_CLOUD_LOCATION"] = ae_location
    vertexai.init(
        project=project_id,
        location=ae_location,
        staging_bucket=staging_bucket,
    )

    # Read requirements.
    requirements = _read_requirements()
    ae_req = "google-cloud-aiplatform[agent_engines,adk]>=1.121.0"
    if not any("google-cloud-aiplatform" in r for r in requirements):
        requirements.append(ae_req)
    requirements = _pin_all_requirements(requirements)
    print(f"   {len(requirements)} dependencies")

    # Stage source packages.
    raw_packages = [
        agent_path,
        "agents/utils",
        "agents/__init__.py",
        "agents/skills",
        "gen_proto",
        *cfg.get("extra_packages", []),
    ]
    staging_dir, staged_packages = _stage_extra_packages(raw_packages)
    print(f"   Staged {len(staged_packages)} packages to {staging_dir}")

    build_fingerprint = _compute_staging_fingerprint(staging_dir)
    print(f"   Build fingerprint: {build_fingerprint}")

    # Import the agent module.
    os.environ["DISPATCH_MODE"] = "callable"
    os.environ["BUILD_FINGERPRINT"] = build_fingerprint
    print(f"   Importing {module_path}:{attr_name}...")
    mod = importlib.import_module(module_path)
    a2a_agent = getattr(mod, attr_name)

    # Create vs. update. Location for AE list/get is implicit from the
    # vertexai.init(project=..., location=ae_location) call earlier in
    # this function -- no per-helper parameter needed.
    mode, existing_resource = _determine_deploy_mode(service_name, force_create=force_create)

    previous_fingerprint = None
    if mode == "update" and existing_resource:
        previous_fingerprint = _fetch_current_card_version(existing_resource, ae_location)
        if previous_fingerprint:
            if previous_fingerprint == build_fingerprint:
                print(f"   Code unchanged (fingerprint {build_fingerprint} already serving)")
            else:
                print(f"   Previous fingerprint: {previous_fingerprint}")

    # Build env vars for Agent Engine.
    redis_addr = f"{tf['redis_host']}:{tf['redis_port']}" if tf["redis_host"] else ""
    # Best-effort gateway URL discovery. Returns None inside the
    # python:3.13-slim Cloud Build step (no gcloud) or when the gateway
    # is not yet deployed; callers store an empty string in that case.
    gateway_url = _get_gateway_url(project_id, tf["region"]) or ""
    ae_env_vars = {
        "PROJECT_ID": project_id,
        "VERTEXAI_PROJECT": project_id,
        "VERTEXAI_LOCATION": ae_location,
        "DISPATCH_MODE": "callable",
        "GATEWAY_URL": gateway_url,
        "GATEWAY_INTERNAL_URL": gateway_url,
        "REDIS_ADDR": redis_addr,
        "REDIS_MAX_CONNECTIONS": "10",
        "PUBSUB_PROJECT_ID": project_id,
        "PUBSUB_TOPIC_ID": tf["pubsub_topic"],
        "ORCHESTRATION_TOPIC_ID": tf["orchestration_topic"],
        "GOOGLE_CLOUD_LOCATION": "global",
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "LITELLM_TELEMETRY": "False",
        "BUILD_FINGERPRINT": build_fingerprint,
    }

    # Simulation defaults.
    for sim_key in (
        "SIM_DEFAULT_DURATION_SECONDS",
        "SIM_DEFAULT_TICK_INTERVAL_SECONDS",
    ):
        val = os.getenv(sim_key)
        if val:
            ae_env_vars[sim_key] = val

    # Propagate peer AE agent URLs.
    for svc_key, svc_cfg in SERVICES.items():
        if svc_cfg["type"] == "reasoning-engine":
            url = os.getenv(f"{svc_key.upper()}_INTERNAL_URL", "")
            if url:
                ae_env_vars[f"{svc_key.upper()}_INTERNAL_URL"] = url

    # Database wiring for planner_with_memory's route store + rules tools.
    # The agent code reads env vars named ``ALLOYDB_*`` regardless of the
    # actual backend; in OSS those are wired to the Cloud SQL instance
    # provisioned by Terraform (``database_ip`` resolves to the Cloud SQL
    # private IP because ``enable_alloydb`` defaults to false). The
    # ``USE_ALLOYDB=false`` switch flips the agent's tool layer to its
    # Cloud SQL + Vertex AI embedding code path
    # (see agents/planner_with_memory/memory/tools.py:_resolve_embedding_backend).
    db_host = tf.get("database_ip") or ""
    db_type = tf.get("database_type") or "cloud-sql"
    db_secret_id = tf.get("database_password_secret_id") or ""
    # cloud-sql-postgres module names its database "agent_memory" by
    # default. Tracked as a tf output for forward-compat in case the
    # name becomes configurable.
    db_name = tf.get("database_name") or "agent_memory"
    if db_host:
        ae_env_vars["USE_ALLOYDB"] = "true" if db_type == "alloydb" else "false"
        ae_env_vars["ALLOYDB_HOST"] = db_host
        ae_env_vars["ALLOYDB_USER"] = "postgres"
        ae_env_vars["ALLOYDB_DATABASE"] = db_name
        ae_env_vars["ALLOYDB_SCHEMA"] = "public"
        if db_secret_id:
            # Vertex AI Agent Engine env supports Secret Manager refs as
            # dicts: ``{"secret": "<secret-id>", "version": "latest"}``.
            ae_env_vars["ALLOYDB_PASSWORD"] = {
                "secret": db_secret_id,
                "version": "latest",
            }

    # Strip empty values: Vertex AI's reasoning_engine.spec.deployment_spec.env
    # validator rejects "Required field is not set" when an env var has an
    # empty value (e.g. GATEWAY_URL during the bootstrap phase, before the
    # Cloud Run gateway has been deployed by tf-apply-services). Missing keys
    # are accepted; empty values are not. Any vars stripped here can be
    # populated post-bootstrap by an explicit AE update. Secret-ref dict
    # values pass through (the != "" comparison is False for non-strings).
    ae_env_vars = {k: v for k, v in ae_env_vars.items() if v != ""}

    # PSC network attachment (from Terraform or env).
    psc_attachment = tf.get("psc_network_attachment")
    psc_config = None
    if psc_attachment:
        psc_config = {"network_attachment": psc_attachment}

    # Service account from Terraform.
    sa = tf.get("agent_engine_sa_email", "")

    # Deploy.
    from vertexai import agent_engines

    original_dir = os.getcwd()
    os.chdir(staging_dir)
    try:
        # Resource floor: 2Gi/1CPU per-service in the SERVICES dict
        # (the AE container is mostly waiting on Gemini API responses).
        resource_limits = cfg.get("resource_limits", {"memory": "2Gi", "cpu": "1"})

        # min_instances/max_instances intentionally not set unless the
        # SERVICES cfg overrides: AE's defaults give scale-to-zero
        # between simulations and a sensible burst cap.
        deploy_kwargs = dict(
            agent_engine=a2a_agent,
            display_name=service_name,
            description=f"{service_name} agent",
            requirements=requirements,
            extra_packages=staged_packages,
            env_vars=ae_env_vars,
            min_instances=cfg.get("min_instances", 0),
            resource_limits=resource_limits,
            container_concurrency=5,
            gcs_dir_name=f"agent_engine/{service_name}",
        )
        if "max_instances" in cfg:
            deploy_kwargs["max_instances"] = cfg["max_instances"]
        if psc_config:
            deploy_kwargs["psc_interface_config"] = psc_config
        if sa:
            deploy_kwargs["service_account"] = sa
        if mode == "update":
            assert existing_resource is not None
            print(f"\n   Updating existing Agent Engine ({existing_resource})...")
            deploy_kwargs["resource_name"] = existing_resource
            deployed = agent_engines.update(**deploy_kwargs)
        else:
            print("\n   Creating new Agent Engine...")
            deployed = agent_engines.create(**deploy_kwargs)
    finally:
        os.chdir(original_dir)
        shutil.rmtree(staging_dir, ignore_errors=True)

    resource_name = deployed.resource_name
    agent_engine_id = resource_name.split("/")[-1]
    a2a_url = _build_resource_url(resource_name, ae_location)

    print(f"\n  Agent Engine deployed.")
    print(f"   Resource:     {resource_name}")
    print(f"   Engine ID:    {agent_engine_id}")
    print(f"   A2A Endpoint: {a2a_url}")
    print(f"\n   Set this env var for gateway discovery:")
    print(f"   {service_name.upper()}_INTERNAL_URL={a2a_url}")

    _verify_deployed_agent(
        service_name,
        resource_name,
        ae_location,
        expected_fingerprint=build_fingerprint,
        previous_fingerprint=previous_fingerprint,
    )

    # Restore GOOGLE_CLOUD_LOCATION.
    if saved_location is not None:
        os.environ["GOOGLE_CLOUD_LOCATION"] = saved_location
    else:
        os.environ.pop("GOOGLE_CLOUD_LOCATION", None)

    return a2a_url


# --- CLI ---


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deploy a single Agent Engine agent to Vertex AI. Used by the "
            "OSS one-shot orchestrator (cloudbuild-bootstrap.yaml)."
        )
    )
    parser.add_argument("--project", help="GCP Project ID override")
    parser.add_argument("--region", help="GCP Region override")
    parser.add_argument(
        "--force-create",
        action="store_true",
        help="Force creation of new Agent Engines (skip update-in-place)",
    )
    parser.add_argument(
        "--only",
        required=True,
        help=(
            "Deploy ONLY the named agent (one of: " + ", ".join(SERVICES) + "). "
            "Used by the Cloud Build orchestrator (cloudbuild-bootstrap.yaml) "
            "to deploy individual Agent Engine agents in parallel."
        ),
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help=(
            "After deployment, print ONLY the deployed resource URL on the "
            "final line of stdout (for shell capture in Cloud Build steps "
            "via `... | tail -1`)."
        ),
    )

    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        env_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            ".env",
        )
        if os.path.isfile(env_file):
            print(f"  Loading environment from {env_file}")
            load_dotenv(env_file, override=True)
    except ImportError:
        pass

    # Read infrastructure values.
    tf = _read_terraform_outputs()

    if args.project:
        tf["project_id"] = args.project
    if args.region:
        tf["region"] = args.region

    if args.only not in SERVICES:
        parser.error(f"unknown agent for --only: {args.only!r} (known: {', '.join(SERVICES)})")

    cfg = SERVICES[args.only]
    url = deploy_agent_engine(args.only, cfg, tf=tf, force_create=args.force_create)
    if args.print_url and url:
        # MUST be the final line of stdout (Cloud Build captures via tail -1).
        print(url)


if __name__ == "__main__":
    main()
