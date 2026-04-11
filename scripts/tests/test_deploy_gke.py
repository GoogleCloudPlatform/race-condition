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

"""Tests for GKE service type in deploy.py."""

import importlib
import os
from unittest.mock import patch

import pytest


class TestRunnerGkeServiceConfig:
    """Verify runner_gke is registered in SERVICES with correct config."""

    def test_runner_gke_in_services(self):
        from scripts.deploy.deploy import SERVICES

        assert "runner_gke" in SERVICES

    def test_runner_gke_type_is_gke(self):
        from scripts.deploy.deploy import SERVICES

        assert SERVICES["runner_gke"]["type"] == "gke"

    def test_runner_gke_is_agent(self):
        from scripts.deploy.deploy import SERVICES

        assert SERVICES["runner_gke"].get("agent") is True

    def test_runner_gke_reuses_runner_cloudrun_image(self):
        from scripts.deploy.deploy import SERVICES

        assert SERVICES["runner_gke"]["image"] == "runner_cloudrun"

    def test_runner_gke_cluster_config(self):
        from scripts.deploy.deploy import SERVICES

        cfg = SERVICES["runner_gke"]
        assert cfg["cluster"] == "runner-cluster"
        assert cfg["namespace"] == "runner"

    def test_runner_gke_cloud_run_name(self):
        from scripts.deploy.deploy import _cloud_run_name

        assert _cloud_run_name("runner_gke") == "runner-gke"


class TestAgentUrlsIncludesGke:
    """Verify AGENT_URLS includes GKE agent URLs for gateway discovery."""

    @patch.dict(
        os.environ,
        {
            "RUNNER_GKE_INTERNAL_URL": "http://10.9.0.50:8207",
        },
    )
    def test_gateway_agent_urls_includes_gke_url(self):
        """When RUNNER_GKE_INTERNAL_URL is set, it appears in AGENT_URLS."""
        # Need to reload to pick up the patched env
        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        env_vars = deploy_mod.build_env_vars("gateway", project_id="test-project")
        agent_urls_entry = [v for v in env_vars if v.startswith("AGENT_URLS=")]
        assert len(agent_urls_entry) == 1
        assert "http://10.9.0.50:8207" in agent_urls_entry[0]

    def test_gateway_agent_urls_omits_gke_when_no_url(self):
        """When RUNNER_GKE_INTERNAL_URL is not set, it should not appear."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RUNNER_GKE_INTERNAL_URL", None)
            import scripts.deploy.deploy as deploy_mod

            importlib.reload(deploy_mod)
            env_vars = deploy_mod.build_env_vars("gateway", project_id="test-project")
            agent_urls_entry = [v for v in env_vars if v.startswith("AGENT_URLS=")]
            # If AGENT_URLS exists, the GKE URL should not be in it
            if agent_urls_entry:
                assert "10.9.0.50" not in agent_urls_entry[0]
