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

"""Tests for deploy.py build_env_vars dispatch mode, AGENT_URLS wiring, and source staging."""

import importlib
import os
import shutil

import pytest
from unittest.mock import MagicMock, patch

import scripts.deploy.deploy as deploy


@pytest.fixture(autouse=True)
def _reset_deploy_module(monkeypatch):
    """Ensure deploy module globals don't leak between tests."""
    monkeypatch.setenv("ENV_NAME", "test")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")


def test_runner_autopilot_gets_dispatch_mode_subscriber():
    """runner_autopilot should get DISPATCH_MODE=subscriber."""
    from scripts.deploy.deploy import build_env_vars

    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env_vars = build_env_vars("runner_autopilot")

    assert "DISPATCH_MODE=subscriber" in env_vars


def test_gateway_agent_urls_includes_runner_autopilot(monkeypatch):
    """Gateway AGENT_URLS should include runner_autopilot internal URL."""
    from scripts.deploy.deploy import build_env_vars

    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env_vars = build_env_vars("gateway")

    agent_url_vars = [v for v in env_vars if v.startswith("AGENT_URLS=")]
    assert len(agent_url_vars) == 1
    urls = agent_url_vars[0].split("=", 1)[1].split(",")
    assert any("runner-autopilot-123456" in u for u in urls), "Should include runner-autopilot internal URL"


def test_non_runner_no_dispatch_mode():
    """Non-runner Cloud Run services should NOT get DISPATCH_MODE."""
    from scripts.deploy.deploy import build_env_vars

    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env_vars = build_env_vars("gateway")

    dispatch_vars = [v for v in env_vars if v.startswith("DISPATCH_MODE=")]
    # Gateway should not have its own DISPATCH_MODE
    assert not dispatch_vars


def test_gateway_gets_agent_urls(monkeypatch):
    """Gateway should get AGENT_URLS with runner internal URL + AE agent URLs."""
    from scripts.deploy.deploy import build_env_vars

    monkeypatch.setenv("SIMULATOR_INTERNAL_URL", "https://sim.example.com")
    monkeypatch.setenv("PLANNER_INTERNAL_URL", "https://plan.example.com")

    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env_vars = build_env_vars("gateway")

    agent_url_vars = [v for v in env_vars if v.startswith("AGENT_URLS=")]
    assert len(agent_url_vars) == 1

    urls = agent_url_vars[0].split("=", 1)[1].split(",")
    assert any("runner-autopilot-123456" in u for u in urls), "Should include runner-autopilot internal URL"
    assert "https://sim.example.com" in urls, "Should include simulator AE URL"
    assert "https://plan.example.com" in urls, "Should include planner AE URL"


def test_gateway_no_agent_urls_without_project_number():
    """Gateway without project number should still include AE URLs if set."""
    from scripts.deploy.deploy import build_env_vars

    with patch("scripts.deploy.deploy._get_project_number", return_value=""):
        env_vars = build_env_vars("gateway")

    # Without project number, no runner internal URL, and no AE URLs set
    agent_url_vars = [v for v in env_vars if v.startswith("AGENT_URLS=")]
    assert not agent_url_vars, "No AGENT_URLS if no URLs available"


# --- Source staging tests ---


@pytest.fixture
def fake_packages(tmp_path):
    """Create a realistic fake agent package structure for testing."""
    # Simulate agents/simulator/
    agent_dir = tmp_path / "agents" / "simulator"
    agent_dir.mkdir(parents=True)
    (agent_dir / "__init__.py").write_text("# init")
    (agent_dir / "agent.py").write_text("# agent code")
    (agent_dir / "README.md").write_text("# Docs")
    (agent_dir / "test_simulator_agent.py").write_text("# test")
    (agent_dir / "simulator_test.py").write_text("# test")

    # __pycache__
    pycache = agent_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "agent.cpython-313.pyc").write_bytes(b"\x00" * 100)

    # .adk/ local state
    adk_dir = agent_dir / ".adk"
    adk_dir.mkdir()
    (adk_dir / "session.db").write_bytes(b"\x00" * 36864)

    # tests/ directory
    tests_dir = agent_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_tools.py").write_text("# test")

    # skills/ directory (should be kept)
    skills_dir = agent_dir / "skills" / "sim-execution"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# skill docs")
    (skills_dir / "tools.py").write_text("# skill tools")

    # Simulate agents/utils/
    utils_dir = tmp_path / "agents" / "utils"
    utils_dir.mkdir(parents=True)
    (utils_dir / "__init__.py").write_text("# init")
    (utils_dir / "a2a.py").write_text("# a2a code")
    (utils_dir / "communication.py").write_text("# comms")
    (utils_dir / "communication_test.py").write_text("# test")
    (utils_dir / "test_config.py").write_text("# test")
    (utils_dir / "README.md").write_text("# docs")
    utils_pycache = utils_dir / "__pycache__"
    utils_pycache.mkdir()
    (utils_pycache / "a2a.cpython-313.pyc").write_bytes(b"\x00" * 50)

    # Simulate gen_proto/
    gen_proto = tmp_path / "gen_proto"
    gen_proto.mkdir()
    (gen_proto / "__init__.py").write_text("# init")
    gateway_dir = gen_proto / "gateway"
    gateway_dir.mkdir()
    (gateway_dir / "__init__.py").write_text("# init")
    (gateway_dir / "gateway_pb2.py").write_text("# generated python")
    (gateway_dir / "gateway_pb2.pyi").write_text("# type stubs")
    (gateway_dir / "gateway.pb.go").write_text("// generated go")
    (gateway_dir / "gateway.proto").write_text("syntax = 'proto3';")

    # Simulate agents/__init__.py
    (tmp_path / "agents" / "__init__.py").write_text("# agents init")

    return tmp_path


class TestStageExtraPackages:
    """Tests for _stage_extra_packages().

    All tests use ``monkeypatch.chdir(fake_packages)`` so that relative
    paths like ``"agents/simulator"`` resolve correctly, matching how
    ``deploy_agent_engine()`` calls the function in production.
    """

    def test_excludes_pycache(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/utils",
            "gen_proto",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            for root, dirs, _files in os.walk(staging_dir):
                assert "__pycache__" not in dirs, f"Found __pycache__ in {root}"
        finally:
            shutil.rmtree(staging_dir)

    def test_excludes_test_files(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/utils",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            all_files = []
            for root, _dirs, files in os.walk(staging_dir):
                all_files.extend(files)
            test_files = [f for f in all_files if f.startswith("test_") or f.endswith("_test.py")]
            assert test_files == [], f"Found test files: {test_files}"
        finally:
            shutil.rmtree(staging_dir)

    def test_excludes_adk_state(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = ["agents/simulator"]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            for root, dirs, _files in os.walk(staging_dir):
                assert ".adk" not in dirs, f"Found .adk in {root}"
        finally:
            shutil.rmtree(staging_dir)

    def test_excludes_go_and_proto_source(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = ["gen_proto"]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            all_files = []
            for root, _dirs, files in os.walk(staging_dir):
                all_files.extend(files)
            assert "gateway.pb.go" not in all_files
            assert "gateway.proto" not in all_files
            assert "gateway_pb2.py" in all_files
            assert "__init__.py" in all_files
        finally:
            shutil.rmtree(staging_dir)

    def test_excludes_test_directories(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = ["agents/simulator"]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            for root, dirs, _files in os.walk(staging_dir):
                assert "tests" not in dirs, f"Found tests/ dir in {root}"
        finally:
            shutil.rmtree(staging_dir)

    def test_keeps_essential_files(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/utils",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            all_files = []
            for root, _dirs, files in os.walk(staging_dir):
                all_files.extend(files)
            assert "agent.py" in all_files
            assert "__init__.py" in all_files
            assert "a2a.py" in all_files
            assert "communication.py" in all_files
            assert "tools.py" in all_files
        finally:
            shutil.rmtree(staging_dir)

    def test_handles_single_file(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = ["agents/__init__.py"]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            assert len(staged) == 1
            assert staged[0] == "agents"
            assert os.path.isfile(os.path.join(staging_dir, "agents", "__init__.py"))
        finally:
            shutil.rmtree(staging_dir)

    def test_returns_correct_staged_paths(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/__init__.py",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            # Should return top-level entries ("agents") not individual subpaths
            assert len(staged) == 1, f"Expected 1 top-level entry, got {staged}"
            assert staged[0] == "agents", f"Expected 'agents', got {staged[0]}"
            # The entry should exist inside the staging directory
            assert os.path.exists(os.path.join(staging_dir, staged[0]))
        finally:
            shutil.rmtree(staging_dir)

    def test_preserves_parent_directory_hierarchy(self, fake_packages, monkeypatch):
        """Staged packages must preserve their parent directory structure.

        The SDK's tarfile.add() uses the file path as the archive member name.
        If we stage "agents/simulator" as just "simulator" at the top level,
        the AE server won't find the "agents" package. The staged structure
        must be:
            staging_dir/agents/simulator/
            staging_dir/agents/utils/
            staging_dir/agents/__init__.py
            staging_dir/gen_proto/
        """
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/utils",
            "agents/__init__.py",
            "gen_proto",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            # agents/ parent directory must exist
            assert os.path.isdir(os.path.join(staging_dir, "agents")), (
                "agents/ parent directory missing -- hierarchy not preserved"
            )
            # agents/__init__.py must be at the right level
            assert os.path.isfile(os.path.join(staging_dir, "agents", "__init__.py")), (
                "agents/__init__.py missing from correct path"
            )
            # agents/simulator/ must be nested under agents/
            assert os.path.isdir(os.path.join(staging_dir, "agents", "simulator")), (
                "agents/simulator/ not nested under agents/"
            )
            # agents/utils/ must be nested under agents/
            assert os.path.isdir(os.path.join(staging_dir, "agents", "utils")), "agents/utils/ not nested under agents/"
            # gen_proto/ at top level (no parent to preserve)
            assert os.path.isdir(os.path.join(staging_dir, "gen_proto")), "gen_proto/ missing from staging"
            # Staged paths must be relative (top-level entries in staging_dir)
            # so the SDK's tar.add() produces correct archive member names
            for p in staged:
                assert not os.path.isabs(p), f"Staged path must be relative, got absolute: {p}"
        finally:
            shutil.rmtree(staging_dir)

    def test_excludes_readme_but_keeps_skill_md(self, fake_packages, monkeypatch):
        monkeypatch.chdir(fake_packages)
        from scripts.deploy.deploy import _stage_extra_packages

        extra = [
            "agents/simulator",
            "agents/utils",
        ]
        staging_dir, staged = _stage_extra_packages(extra)
        try:
            all_files = []
            for root, _dirs, files in os.walk(staging_dir):
                all_files.extend(files)
            # README.md should be excluded
            assert "README.md" not in all_files, "README.md should be excluded"
            # SKILL.md should be kept (ADK skill definitions)
            assert "SKILL.md" in all_files, "SKILL.md should be kept for ADK"
        finally:
            shutil.rmtree(staging_dir)


# --- MIN_INSTANCES configuration tests ---


class TestMinInstances:
    """Tests for configurable MIN_INSTANCES."""

    def test_default_min_instances_is_one(self, monkeypatch):
        """MIN_INSTANCES defaults to 1 when not set."""
        monkeypatch.delenv("MIN_INSTANCES", raising=False)
        import importlib

        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        assert deploy_mod.MIN_INSTANCES == 1

    def test_min_instances_reads_from_env(self, monkeypatch):
        """MIN_INSTANCES reads from environment variable."""
        monkeypatch.setenv("MIN_INSTANCES", "5")
        import importlib

        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        assert deploy_mod.MIN_INSTANCES == 5

    def test_min_instances_used_as_string(self, monkeypatch):
        """MIN_INSTANCES should be usable as a string for CLI args."""
        monkeypatch.setenv("MIN_INSTANCES", "3")
        import importlib

        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        assert str(deploy_mod.MIN_INSTANCES) == "3"

    def test_invalid_min_instances_falls_back_to_default(self, monkeypatch):
        """Non-integer MIN_INSTANCES should fall back to default of 1."""
        monkeypatch.setenv("MIN_INSTANCES", "foo")
        import importlib

        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        assert deploy_mod.MIN_INSTANCES == 1

    def test_negative_min_instances_falls_back_to_default(self, monkeypatch):
        """Negative MIN_INSTANCES should fall back to default of 1."""
        monkeypatch.setenv("MIN_INSTANCES", "-5")
        import importlib

        import scripts.deploy.deploy as deploy_mod

        importlib.reload(deploy_mod)
        assert deploy_mod.MIN_INSTANCES == 1


class TestRedisMaxConnections:
    """Tests for REDIS_MAX_CONNECTIONS injection for high-throughput runners."""

    def test_runner_autopilot_gets_redis_max_connections(self):
        """runner_autopilot should get REDIS_MAX_CONNECTIONS=100."""
        from scripts.deploy.deploy import build_env_vars

        with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
            env_vars = build_env_vars("runner_autopilot")

        assert "REDIS_MAX_CONNECTIONS=100" in env_vars
        assert "REDIS_SESSION_MAX_CONNECTIONS=100" in env_vars

    def test_gateway_no_redis_max_connections(self):
        """Non-runner services should NOT get REDIS_MAX_CONNECTIONS."""
        from scripts.deploy.deploy import build_env_vars

        with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
            env_vars = build_env_vars("gateway")

        redis_max_vars = [v for v in env_vars if v.startswith("REDIS_MAX_CONNECTIONS=")]
        assert not redis_max_vars


class TestExtractResourceName:
    """Tests for _extract_resource_name()."""

    def test_extracts_from_v1beta1_url(self):
        from scripts.deploy.deploy import _extract_resource_name

        url = (
            "https://us-central1-aiplatform.googleapis.com/v1beta1/"
            "projects/123456789012/locations/us-central1/"
            "reasoningEngines/1012394022972424192"
        )
        assert _extract_resource_name(url) == (
            "projects/123456789012/locations/us-central1/reasoningEngines/1012394022972424192"
        )

    def test_returns_none_for_non_ae_url(self):
        from scripts.deploy.deploy import _extract_resource_name

        url = "https://runner-dev.sim.example.test"
        assert _extract_resource_name(url) is None

    def test_returns_none_for_empty_string(self):
        from scripts.deploy.deploy import _extract_resource_name

        assert _extract_resource_name("") is None

    def test_returns_none_for_malformed_url(self):
        from scripts.deploy.deploy import _extract_resource_name

        assert _extract_resource_name("not-a-url") is None


class TestVerifyDeployedAgent:
    """Tests for _verify_deployed_agent()."""

    @patch("scripts.deploy.deploy.time.sleep")
    @patch("scripts.deploy.deploy.requests.get")
    @patch("scripts.deploy.deploy.google.auth.default")
    def test_returns_true_on_name_match(self, mock_auth, mock_get, mock_sleep):
        from scripts.deploy.deploy import _verify_deployed_agent

        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_auth.return_value = (mock_creds, "project-id")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "simulator"}
        mock_get.return_value = mock_resp

        result = _verify_deployed_agent(
            "simulator",
            "projects/123/locations/us-central1/reasoningEngines/456",
            "us-central1",
        )
        assert result is True

    @patch("scripts.deploy.deploy.time.sleep")
    @patch("scripts.deploy.deploy.requests.get")
    @patch("scripts.deploy.deploy.google.auth.default")
    def test_returns_false_on_name_mismatch(self, mock_auth, mock_get, mock_sleep):
        from scripts.deploy.deploy import _verify_deployed_agent

        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_auth.return_value = (mock_creds, "project-id")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "debug"}
        mock_get.return_value = mock_resp

        result = _verify_deployed_agent(
            "simulator",
            "projects/123/locations/us-central1/reasoningEngines/456",
            "us-central1",
        )
        assert result is False

    @patch("scripts.deploy.deploy.time.sleep")
    @patch("scripts.deploy.deploy.requests.get")
    @patch("scripts.deploy.deploy.google.auth.default")
    def test_returns_none_on_timeout(self, mock_auth, mock_get, mock_sleep):
        from scripts.deploy.deploy import _verify_deployed_agent

        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_auth.return_value = (mock_creds, "project-id")

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        result = _verify_deployed_agent(
            "simulator",
            "projects/123/locations/us-central1/reasoningEngines/456",
            "us-central1",
            timeout=1,
            interval=0.5,
        )
        assert result is None

    @patch("scripts.deploy.deploy.time.sleep")
    @patch("scripts.deploy.deploy.requests.get")
    @patch("scripts.deploy.deploy.google.auth.default")
    def test_retries_on_connection_error(self, mock_auth, mock_get, mock_sleep):
        from scripts.deploy.deploy import _verify_deployed_agent

        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        mock_auth.return_value = (mock_creds, "project-id")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "simulator"}
        mock_get.side_effect = [ConnectionError("not ready"), mock_resp]

        result = _verify_deployed_agent(
            "simulator",
            "projects/123/locations/us-central1/reasoningEngines/456",
            "us-central1",
            timeout=30,
            interval=1,
        )
        assert result is True


class TestDeployMode:
    """Tests for _determine_deploy_mode()."""

    def test_updates_when_engine_exists(self, monkeypatch):
        """When INTERNAL_URL env var points to an existing engine, use update()."""
        from scripts.deploy.deploy import _determine_deploy_mode

        monkeypatch.setenv(
            "SIMULATOR_INTERNAL_URL",
            "https://us-central1-aiplatform.googleapis.com/v1beta1/"
            "projects/123/locations/us-central1/reasoningEngines/456",
        )

        with patch("vertexai.agent_engines.get") as mock_get:
            mode, resource_name = _determine_deploy_mode("simulator", force_create=False)

        assert mode == "update"
        assert resource_name == "projects/123/locations/us-central1/reasoningEngines/456"
        mock_get.assert_called_once()

    def test_creates_when_no_env_var(self, monkeypatch):
        """When no INTERNAL_URL env var exists, use create()."""
        from scripts.deploy.deploy import _determine_deploy_mode

        monkeypatch.delenv("SIMULATOR_INTERNAL_URL", raising=False)
        mode, resource_name = _determine_deploy_mode("simulator", force_create=False)

        assert mode == "create"
        assert resource_name is None

    def test_creates_when_engine_gone(self, monkeypatch):
        """When INTERNAL_URL points to deleted engine, fall back to create()."""
        from scripts.deploy.deploy import _determine_deploy_mode

        monkeypatch.setenv(
            "SIMULATOR_INTERNAL_URL",
            "https://us-central1-aiplatform.googleapis.com/v1beta1/"
            "projects/123/locations/us-central1/reasoningEngines/456",
        )

        with patch("vertexai.agent_engines.get", side_effect=Exception("404 Not Found")):
            mode, resource_name = _determine_deploy_mode("simulator", force_create=False)

        assert mode == "create"
        assert resource_name is None

    def test_force_create_ignores_existing(self, monkeypatch):
        """--force-create always uses create(), even if engine exists."""
        from scripts.deploy.deploy import _determine_deploy_mode

        monkeypatch.setenv(
            "SIMULATOR_INTERNAL_URL",
            "https://us-central1-aiplatform.googleapis.com/v1beta1/"
            "projects/123/locations/us-central1/reasoningEngines/456",
        )

        mode, resource_name = _determine_deploy_mode("simulator", force_create=True)
        assert mode == "create"
        assert resource_name is None

    def test_creates_when_url_is_not_ae(self, monkeypatch):
        """When INTERNAL_URL is a Cloud Run URL (not AE), use create()."""
        from scripts.deploy.deploy import _determine_deploy_mode

        monkeypatch.setenv(
            "SIMULATOR_INTERNAL_URL",
            "https://runner-dev.sim.example.test",
        )

        mode, resource_name = _determine_deploy_mode("simulator", force_create=False)
        assert mode == "create"
        assert resource_name is None


# --- runner_cloudrun tests ---


def test_runner_cloudrun_gets_dispatch_mode_subscriber(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("DOMAIN", "sim.example.test")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")
    importlib.reload(deploy)
    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env = deploy.build_env_vars("runner_cloudrun")
    assert "DISPATCH_MODE=subscriber" in env
    assert "REDIS_MAX_CONNECTIONS=100" in env
    assert "REDIS_SESSION_MAX_CONNECTIONS=100" in env
    assert "SESSION_STORE_OVERRIDE=redis" in env


def test_runner_cloudrun_no_database_url_secret(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("DOMAIN", "sim.example.test")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")
    importlib.reload(deploy)
    assert "DATABASE_URL" not in deploy.SERVICES["runner_cloudrun"].get("secrets", {})


def test_gateway_agent_urls_includes_runner_cloudrun(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("DOMAIN", "sim.example.test")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")
    importlib.reload(deploy)
    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env = deploy.build_env_vars("gateway")
    agent_urls = [v for v in env if v.startswith("AGENT_URLS=")]
    assert len(agent_urls) == 1
    assert "runner-cloudrun-123456" in agent_urls[0]


# --- autopilot cleanup & DATABASE_URL removal tests ---


def test_runner_autopilot_min_instances_is_56():
    assert deploy.SERVICES["runner_autopilot"]["min_instances"] == 56


def test_runner_autopilot_no_database_url_secret():
    secrets = deploy.SERVICES["runner_autopilot"].get("secrets", {})
    assert "DATABASE_URL" not in secrets


def test_runner_autopilot_no_db_pool_env_vars(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("DOMAIN", "sim.example.test")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")
    importlib.reload(deploy)
    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env = deploy.build_env_vars("runner_autopilot")
    db_vars = [v for v in env if v.startswith(("DB_POOL_SIZE=", "DB_MAX_OVERFLOW="))]
    assert len(db_vars) == 0


def test_no_service_gets_database_url(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("DOMAIN", "sim.example.test")
    monkeypatch.setenv("TARGET_PROJECT_ID", "test-project")
    monkeypatch.setenv("REDIS_ADDR", "10.0.0.1:6379")
    importlib.reload(deploy)
    with patch("scripts.deploy.deploy._get_project_number", return_value="123456"):
        env = deploy.build_env_vars("gateway")
    db_vars = [v for v in env if v.startswith("DATABASE_URL=")]
    assert len(db_vars) == 0
