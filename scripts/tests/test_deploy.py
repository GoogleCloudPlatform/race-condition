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

"""Tests for deploy.py — per-service domain URL construction and env var generation."""

import importlib
from urllib.parse import urlparse


# Import deploy module from scripts/deploy/
deploy = importlib.import_module("scripts.deploy.deploy")


class TestServiceURLConstruction:
    """Verify per-service domain pattern replaces path-based routing."""

    def test_gateway_url_uses_per_service_domain(self):
        """GATEWAY_URL should be https://gateway.{env}.{domain}."""
        env_vars = deploy.build_env_vars("gateway", env_name="dev", domain="keynote2026.cloud-demos.goog")
        gateway_url = next(v for v in env_vars if v.startswith("GATEWAY_URL="))
        assert gateway_url == "GATEWAY_URL=https://gateway.dev.keynote2026.cloud-demos.goog"

    def test_runner_autopilot_url_uses_per_service_domain(self):
        """RUNNER_AUTOPILOT_URL should use dashes in domain (Cloud Run naming)."""
        env_vars = deploy.build_env_vars("runner_autopilot", env_name="dev", domain="keynote2026.cloud-demos.goog")
        ra_url = next(v for v in env_vars if v.startswith("RUNNER_AUTOPILOT_URL="))
        assert ra_url == "RUNNER_AUTOPILOT_URL=https://runner-autopilot.dev.keynote2026.cloud-demos.goog"

    def test_no_path_based_urls(self):
        """No service URL should contain path-based routing like /runner or /admin."""
        env_vars = deploy.build_env_vars("gateway", env_name="dev", domain="keynote2026.cloud-demos.goog")
        url_vars = [v for v in env_vars if "_URL=" in v]
        for var in url_vars:
            _, url = var.split("=", 1)
            if not url:
                continue  # Empty URL (e.g., Agent Engine placeholder)
            path = urlparse(url).path
            assert path in ("", "/"), f"{var} has path-based routing: {path}"

    def test_prod_a_domain_pattern(self):
        """Service URLs should adapt to non-dev environments."""
        env_vars = deploy.build_env_vars("admin", env_name="prod-a", domain="keynote2026.cloud-demos.goog")
        admin_url = next(v for v in env_vars if v.startswith("ADMIN_URL="))
        assert admin_url == "ADMIN_URL=https://admin.prod-a.keynote2026.cloud-demos.goog"


class TestCloudModeRemoval:
    """Verify CLOUD_MODE is completely removed."""

    def test_cloud_mode_absent_from_env_vars(self):
        """CLOUD_MODE should not appear in generated env vars."""
        env_vars = deploy.build_env_vars("gateway", env_name="dev", domain="keynote2026.cloud-demos.goog")
        cloud_mode_vars = [v for v in env_vars if "CLOUD_MODE" in v]
        assert cloud_mode_vars == [], f"CLOUD_MODE still present: {cloud_mode_vars}"


class TestNewEnvVars:
    """Verify required cloud env vars are injected."""

    def test_cors_allowed_origins_present(self):
        """CORS_ALLOWED_ORIGINS should be set with per-service UI domains."""
        env_vars = deploy.build_env_vars("gateway", env_name="dev", domain="keynote2026.cloud-demos.goog")
        cors_vars = [v for v in env_vars if v.startswith("CORS_ALLOWED_ORIGINS=")]
        assert len(cors_vars) == 1
        # Should contain at least the UI service domains
        origins = cors_vars[0].split("=", 1)[1]
        assert "tester.dev.keynote2026.cloud-demos.goog" in origins
        assert "admin.dev.keynote2026.cloud-demos.goog" in origins

    def test_database_url_absent(self):
        """DATABASE_URL should NOT be in env vars (AlloyDB removed)."""
        env_vars = deploy.build_env_vars("runner_autopilot", env_name="dev", domain="keynote2026.cloud-demos.goog")
        db_vars = [v for v in env_vars if v.startswith("DATABASE_URL=")]
        assert len(db_vars) == 0

    def test_gcs_artifact_bucket_present(self):
        """GCS_ARTIFACT_BUCKET should be injected."""
        env_vars = deploy.build_env_vars("runner_autopilot", env_name="dev", domain="keynote2026.cloud-demos.goog")
        gcs_vars = [v for v in env_vars if v.startswith("GCS_ARTIFACT_BUCKET=")]
        assert len(gcs_vars) == 1

    def test_iap_client_id_present(self):
        """IAP_CLIENT_ID should be injected."""
        env_vars = deploy.build_env_vars("gateway", env_name="dev", domain="keynote2026.cloud-demos.goog")
        iap_vars = [v for v in env_vars if v.startswith("IAP_CLIENT_ID=")]
        assert len(iap_vars) == 1

    def test_project_id_present(self):
        """PROJECT_ID should be injected."""
        env_vars = deploy.build_env_vars(
            "gateway",
            env_name="dev",
            domain="keynote2026.cloud-demos.goog",
            project_id="n26-devkey-simulation-dev",
        )
        pid_vars = [v for v in env_vars if v.startswith("PROJECT_ID=")]
        assert len(pid_vars) == 1
        assert pid_vars[0] == "PROJECT_ID=n26-devkey-simulation-dev"


class TestAgentEngineServices:
    """Verify Agent Engine list matches architecture decisions."""

    def test_simulator_is_reasoning_engine(self):
        """simulator agent should deploy to Agent Engine."""
        assert deploy.SERVICES["simulator"]["type"] == "reasoning-engine"

    def test_planner_is_reasoning_engine(self):
        """planner agent should deploy to Agent Engine."""
        assert deploy.SERVICES["planner"]["type"] == "reasoning-engine"

    def test_planner_with_eval_is_reasoning_engine(self):
        """planner_with_eval agent should deploy to Agent Engine."""
        assert deploy.SERVICES["planner_with_eval"]["type"] == "reasoning-engine"

    def test_simulator_with_failure_is_reasoning_engine(self):
        """simulator_with_failure agent should deploy to Agent Engine."""
        assert deploy.SERVICES["simulator_with_failure"]["type"] == "reasoning-engine"

    def test_orchestrator_renamed_to_simulation(self):
        """Legacy 'orchestrator' key should not exist — renamed to 'simulation'."""
        assert "orchestrator" not in deploy.SERVICES

    def test_planner_with_memory_is_reasoning_engine(self):
        """planner_with_memory agent should deploy to Agent Engine."""
        assert deploy.SERVICES["planner_with_memory"]["type"] == "reasoning-engine"

    def test_runner_autopilot_is_cloud_run(self):
        """runner_autopilot agent should deploy to Cloud Run."""
        assert deploy.SERVICES["runner_autopilot"]["type"] == "run"

    def test_runner_cloudrun_is_cloud_run(self):
        assert deploy.SERVICES["runner_cloudrun"]["type"] == "run"

    def test_runner_cloudrun_is_agent(self):
        assert deploy.SERVICES["runner_cloudrun"].get("agent")

    def test_runner_autopilot_is_agent(self):
        assert deploy.SERVICES["runner_autopilot"].get("agent")


class TestAgentEngineConfig:
    """Verify Agent Engine SERVICES entries have correct config."""

    def test_planner_with_eval_has_extra_packages(self):
        """planner_with_eval needs agents/planner for evaluation tools."""
        cfg = deploy.SERVICES["planner_with_eval"]
        assert "agents/planner" in cfg.get("extra_packages", [])

    def test_planner_with_memory_has_extra_packages(self):
        """planner_with_memory needs both planner and planner_with_eval ancestors."""
        cfg = deploy.SERVICES["planner_with_memory"]
        assert "agents/planner" in cfg.get("extra_packages", [])
        assert "agents/planner_with_eval" in cfg.get("extra_packages", [])

    def test_planner_with_memory_module_path(self):
        """planner_with_memory module path should point to its agent module."""
        cfg = deploy.SERVICES["planner_with_memory"]
        assert cfg["module"] == "agents.planner_with_memory.agent"

    def test_planner_with_eval_module_path(self):
        """planner_with_eval module path should point to its agent module."""
        cfg = deploy.SERVICES["planner_with_eval"]
        assert cfg["module"] == "agents.planner_with_eval.agent"

    def test_simulator_with_failure_module_path(self):
        """simulator_with_failure module path should point to its agent module."""
        cfg = deploy.SERVICES["simulator_with_failure"]
        assert cfg["module"] == "agents.simulator_with_failure.agent"

    def test_self_contained_agents_have_no_extra_packages(self):
        """Agents without cross-deps should not have extra_packages."""
        for name in ("simulator", "planner", "simulator_with_failure"):
            cfg = deploy.SERVICES[name]
            assert "extra_packages" not in cfg, f"{name} should not have extra_packages"

    def test_all_reasoning_engines_have_required_fields(self):
        """Every reasoning-engine entry needs path, module, and attr."""
        for name, cfg in deploy.SERVICES.items():
            if cfg["type"] == "reasoning-engine":
                assert "path" in cfg, f"{name} missing 'path'"
                assert "module" in cfg, f"{name} missing 'module'"
                assert "attr" in cfg, f"{name} missing 'attr'"
