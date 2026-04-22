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

"""Tests for the OSS deploy.py template.

Pure-function and structural-contract tests; gcloud / terraform are mocked.

The deploy module is loaded via importlib from the sibling file so the same
tests work in the monorepo (templates/) and in a synced OSS repo (where
``import scripts.deploy.deploy`` would bind to the wrong file).
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DEPLOY_PATH = Path(__file__).resolve().parent / "deploy.py"
_spec = importlib.util.spec_from_file_location("oss_template_deploy", _DEPLOY_PATH)
deploy = importlib.util.module_from_spec(_spec)
sys.modules["oss_template_deploy"] = deploy
_spec.loader.exec_module(deploy)


# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the Terraform output cache between tests."""
    deploy._terraform_outputs_cache = None
    yield
    deploy._terraform_outputs_cache = None


def _make_tf(**overrides) -> dict:
    """Build a minimal Terraform outputs dict for testing."""
    base = {
        "project_id": "test-project",
        "region": "us-central1",
        "redis_host": "10.0.0.1",
        "redis_port": "6379",
        "pubsub_topic": "agent-telemetry",
        "orchestration_topic": "specialist-orchestration",
        "agent_engine_sa_email": "agent@test-project.iam.gserviceaccount.com",
        "psc_network_attachment": "",
        "staging_bucket": "",
    }
    base.update(overrides)
    return base


# --- _extract_resource_name ---


class TestExtractResourceName:
    def test_valid_url(self):
        url = "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456"
        assert deploy._extract_resource_name(url) == "projects/123/locations/us-central1/reasoningEngines/456"

    def test_no_v1beta1(self):
        assert deploy._extract_resource_name("https://example.com/foo") is None

    def test_empty_after_prefix(self):
        assert deploy._extract_resource_name("https://example.com/v1beta1/") is None

    def test_trailing_slash(self):
        url = "https://example.com/v1beta1/projects/1/reasoningEngines/2"
        assert deploy._extract_resource_name(url) == "projects/1/reasoningEngines/2"


# --- _get_card_url ---


class TestGetCardUrl:
    def test_builds_correct_url(self):
        result = deploy._get_card_url("projects/1/locations/us-central1/reasoningEngines/2", "us-central1")
        assert (
            result
            == "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/1/locations/us-central1/reasoningEngines/2/a2a/v1/card"
        )


# --- _build_resource_url ---


class TestBuildResourceUrl:
    """Locks the URL shape that main() prints as the final stdout line --
    Cloud Build captures it via ``... | tail -1`` into AGENT_URLS."""

    def test_builds_v1beta1_resource_url(self):
        result = deploy._build_resource_url(
            "projects/1/locations/us-central1/reasoningEngines/2",
            "us-central1",
        )
        assert (
            result
            == "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/1/locations/us-central1/reasoningEngines/2"
        )

    def test_uses_location_in_endpoint(self):
        result = deploy._build_resource_url("projects/p/reasoningEngines/e", "europe-west4")
        assert result.startswith("https://europe-west4-aiplatform.googleapis.com/v1beta1/")


# --- _compute_staging_fingerprint ---


class TestStagingFingerprint:
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("hello")
            fp1 = deploy._compute_staging_fingerprint(d)
            fp2 = deploy._compute_staging_fingerprint(d)
            assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            with open(os.path.join(d1, "a.py"), "w") as f:
                f.write("hello")
            with open(os.path.join(d2, "a.py"), "w") as f:
                f.write("world")
            assert deploy._compute_staging_fingerprint(d1) != deploy._compute_staging_fingerprint(d2)

    def test_length_is_16(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.py"), "w") as f:
                f.write("test")
            assert len(deploy._compute_staging_fingerprint(d)) == 16

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            fp = deploy._compute_staging_fingerprint(d)
            assert isinstance(fp, str)
            assert len(fp) == 16


# --- _staging_ignore ---


class TestStagingIgnore:
    def test_ignores_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        ignored = deploy._staging_ignore(str(tmp_path), ["__pycache__", "agent.py"])
        assert "__pycache__" in ignored
        assert "agent.py" not in ignored

    def test_ignores_test_prefix(self, tmp_path):
        (tmp_path / "test_foo.py").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["test_foo.py", "foo.py"])
        assert "test_foo.py" in ignored

    def test_ignores_test_suffix(self, tmp_path):
        (tmp_path / "foo_test.py").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["foo_test.py"])
        assert "foo_test.py" in ignored

    def test_ignores_pyc(self, tmp_path):
        (tmp_path / "mod.pyc").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["mod.pyc"])
        assert "mod.pyc" in ignored

    def test_ignores_proto(self, tmp_path):
        (tmp_path / "service.proto").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["service.proto"])
        assert "service.proto" in ignored

    def test_ignores_readme(self, tmp_path):
        (tmp_path / "README.md").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["README.md"])
        assert "README.md" in ignored

    def test_keeps_skill_md(self, tmp_path):
        (tmp_path / "SKILL.md").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["SKILL.md"])
        assert "SKILL.md" not in ignored

    def test_keeps_agent_py(self, tmp_path):
        (tmp_path / "agent.py").touch()
        ignored = deploy._staging_ignore(str(tmp_path), ["agent.py"])
        assert "agent.py" not in ignored


# --- SERVICES dict structural validation ---


class TestServicesRegistry:
    """SERVICES must contain exactly the 5 OSS AE agents with all required
    fields and right-sized resource limits (cost regression guard)."""

    def test_only_agent_engine_entries(self):
        for name, cfg in deploy.SERVICES.items():
            assert cfg["type"] == "reasoning-engine", (
                f"{name} has type={cfg['type']!r}; OSS deploy.py only supports "
                "reasoning-engine. Cloud Run/GKE moved to Terraform."
            )

    def test_expected_agents_present(self):
        expected = {
            "planner",
            "simulator",
            "planner_with_eval",
            "simulator_with_failure",
            "planner_with_memory",
        }
        assert set(deploy.SERVICES) == expected

    def test_each_agent_declares_required_fields(self):
        for name, cfg in deploy.SERVICES.items():
            assert "path" in cfg, f"{name} missing 'path'"
            assert "module" in cfg, f"{name} missing 'module'"
            assert "attr" in cfg, f"{name} missing 'attr'"

    def test_no_internal_project_ids(self):
        """No hardcoded internal project references in service configs."""
        serialized = json.dumps(deploy.SERVICES)
        assert "n26-devkey" not in serialized
        assert "keynote2026" not in serialized

    def test_resource_limits_are_right_sized(self):
        """Agent Engine agents use minimal resource limits (cpu<=2, memory<=2Gi)."""
        for name, cfg in deploy.SERVICES.items():
            limits = cfg.get("resource_limits", {})
            cpu = int(limits.get("cpu", "4"))
            assert cpu <= 2, f"{name} has cpu={cpu}, expected <= 2"
            mem = limits.get("memory", "8Gi")
            mem_gb = int(mem.replace("Gi", ""))
            assert mem_gb <= 2, f"{name} has memory={mem}, expected <= 2Gi"

    def test_all_ae_agents_have_at_least_2gi(self):
        """All AE agents need >=2Gi memory: 1Gi causes worker OOMs during
        ADK runtime startup before the health probe gets a 200."""
        for name, cfg in deploy.SERVICES.items():
            mem_gb = int(cfg["resource_limits"]["memory"].replace("Gi", ""))
            assert mem_gb >= 2, (
                f"{name} declares only {mem_gb}Gi memory; OSS-verified "
                f"minimum for AE agents is 2Gi to avoid worker OOM during "
                f"ADK runtime startup."
            )

    def test_max_instances_capped(self):
        for name, cfg in deploy.SERVICES.items():
            mi = cfg.get("max_instances")
            assert mi is not None, f"{name} missing max_instances"
            assert mi <= 1, f"{name} has max_instances={mi}, expected <= 1 for OSS"


# --- _determine_deploy_mode (create-or-update with displayName fallback) ---


class TestDetermineDeployMode:
    """Resolution order: force_create -> {SERVICE}_INTERNAL_URL fast path
    (dev/prod) -> displayName discovery (OSS, prevents orphaning AEs on
    every Cloud Build re-run) -> create."""

    def test_force_create_short_circuits(self):
        mode, resource = deploy._determine_deploy_mode("planner", force_create=True)
        assert mode == "create"
        assert resource is None

    def test_env_var_fast_path_when_engine_exists(self, monkeypatch):
        url = "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/p/locations/us-central1/reasoningEngines/123"
        monkeypatch.setenv("PLANNER_INTERNAL_URL", url)
        with patch.object(deploy, "_lookup_engine_by_resource_name", return_value=True):
            with patch.object(deploy, "_find_engine_by_display_name") as discovery:
                mode, resource = deploy._determine_deploy_mode("planner")
        assert mode == "update"
        assert resource == "projects/p/locations/us-central1/reasoningEngines/123"
        # Discovery is the fallback only -- must NOT run when env var path succeeds.
        discovery.assert_not_called()

    def test_env_var_falls_back_to_discovery_when_engine_missing(self, monkeypatch):
        url = "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/p/locations/us-central1/reasoningEngines/STALE"
        monkeypatch.setenv("PLANNER_INTERNAL_URL", url)
        # Env-var-pointed engine no longer exists; discovery finds a fresh one.
        with patch.object(deploy, "_lookup_engine_by_resource_name", return_value=False):
            with patch.object(
                deploy,
                "_find_engine_by_display_name",
                return_value="projects/p/locations/us-central1/reasoningEngines/FRESH",
            ):
                mode, resource = deploy._determine_deploy_mode("planner")
        assert mode == "update"
        assert resource.endswith("/reasoningEngines/FRESH")

    def test_oss_path_no_env_var_finds_existing_by_display_name(self, monkeypatch):
        # Simulate OSS Cloud Build: no INTERNAL_URL env var of any kind.
        for k in list(os.environ):
            if k.endswith("_INTERNAL_URL"):
                monkeypatch.delenv(k, raising=False)
        with patch.object(
            deploy,
            "_find_engine_by_display_name",
            return_value="projects/p/locations/us-central1/reasoningEngines/DISCOVERED",
        ) as discovery:
            mode, resource = deploy._determine_deploy_mode("planner")
        assert mode == "update"
        assert resource.endswith("/reasoningEngines/DISCOVERED")
        discovery.assert_called_once_with("planner")

    def test_oss_path_no_match_falls_through_to_create(self, monkeypatch):
        for k in list(os.environ):
            if k.endswith("_INTERNAL_URL"):
                monkeypatch.delenv(k, raising=False)
        with patch.object(deploy, "_find_engine_by_display_name", return_value=None):
            mode, resource = deploy._determine_deploy_mode("brand_new_agent")
        assert mode == "create"
        assert resource is None


class TestFindEngineByDisplayName:
    """Returns None on empty list / no match; with multiple matches picks
    the most-recently-updated engine."""

    def test_empty_list_returns_none(self):
        with patch.object(deploy, "_list_reasoning_engines", return_value=[]):
            assert deploy._find_engine_by_display_name("planner") is None

    def test_no_match_returns_none(self):
        from datetime import datetime, timezone

        engines = [
            MagicMock(
                display_name="simulator",
                resource_name="rn-1",
                update_time=datetime(2026, 4, 18, 1, 0, tzinfo=timezone.utc),
            ),
        ]
        with patch.object(deploy, "_list_reasoning_engines", return_value=engines):
            assert deploy._find_engine_by_display_name("planner") is None

    def test_multiple_matches_picks_most_recently_updated(self):
        # Real SDK objects expose update_time as datetime, not str. Use real
        # datetime objects in the mocks so this test exercises the production
        # comparison contract (string-typed mocks would have masked bugs in
        # the sort key against real types -- see code review on commit 5265f6c).
        from datetime import datetime, timezone

        ts = lambda h: datetime(2026, 4, 18, h, 0, 0, tzinfo=timezone.utc)
        engines = [
            MagicMock(display_name="planner", resource_name="rn-old", update_time=ts(1)),
            MagicMock(display_name="planner", resource_name="rn-newer", update_time=ts(3)),
            MagicMock(display_name="planner", resource_name="rn-mid", update_time=ts(2)),
            MagicMock(display_name="simulator", resource_name="rn-other", update_time=ts(5)),
        ]
        with patch.object(deploy, "_list_reasoning_engines", return_value=engines):
            got = deploy._find_engine_by_display_name("planner")
        assert got == "rn-newer"

    def test_match_with_missing_update_time_does_not_typeerror(self):
        # Defensive: a future SDK shape might omit update_time on some entries.
        # The sort key must coerce to a comparable lower bound rather than the
        # default empty string, which would TypeError against datetime peers.
        from datetime import datetime, timezone

        engines = [
            MagicMock(
                display_name="planner",
                resource_name="rn-with-ts",
                update_time=datetime(2026, 4, 18, 1, 0, tzinfo=timezone.utc),
            ),
            MagicMock(spec=["display_name", "resource_name"], display_name="planner", resource_name="rn-no-ts"),
        ]
        with patch.object(deploy, "_list_reasoning_engines", return_value=engines):
            got = deploy._find_engine_by_display_name("planner")
        # The one with the real timestamp wins; the one without is treated as
        # "older than the dawn of time" so it can never beat a real candidate.
        assert got == "rn-with-ts"


class TestListReasoningEngines:
    """Returns [] silently on NotFound (empty project), but re-raises
    permission/quota/network errors -- silent [] would orphan AEs."""

    def test_propagates_permission_denied(self):
        # google.api_core.exceptions.PermissionDenied is the realistic shape;
        # use a stand-in so the test does not depend on importing google api
        # exceptions in this no-network test environment.
        class PermissionDenied(Exception):
            pass

        with patch("vertexai.agent_engines.list", side_effect=PermissionDenied("permission denied")):
            with pytest.raises(PermissionDenied):
                deploy._list_reasoning_engines()

    def test_returns_empty_list_on_not_found(self):
        # NotFound (e.g., reasoningEngines API just enabled, project genuinely
        # has no AEs yet) is the legitimate "first deploy" signal -- return []
        # so discovery falls through to create.
        class NotFound(Exception):
            pass

        with patch("vertexai.agent_engines.list", side_effect=NotFound("not found")):
            assert deploy._list_reasoning_engines() == []


# --- _read_terraform_outputs ---


class TestReadTerraformOutputs:
    @patch("subprocess.run")
    def test_parses_terraform_json(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "project_id": {"value": "my-project", "type": "string"},
                    "region": {"value": "europe-west1", "type": "string"},
                    "redis_host": {"value": "10.1.2.3", "type": "string"},
                }
            ),
            returncode=0,
        )
        result = deploy._read_terraform_outputs()
        assert result["project_id"] == "my-project"
        assert result["region"] == "europe-west1"
        assert result["redis_host"] == "10.1.2.3"

    @patch("subprocess.run", side_effect=FileNotFoundError("terraform not found"))
    def test_falls_back_to_env_vars(self, mock_run, monkeypatch):
        monkeypatch.setenv("PROJECT_ID", "env-project")
        monkeypatch.setenv("REGION", "asia-east1")
        result = deploy._read_terraform_outputs()
        assert result["project_id"] == "env-project"
        assert result["region"] == "asia-east1"

    @patch("subprocess.run")
    def test_caches_result(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"project_id": {"value": "cached", "type": "string"}}),
            returncode=0,
        )
        r1 = deploy._read_terraform_outputs()
        r2 = deploy._read_terraform_outputs()
        assert r1 is r2
        mock_run.assert_called_once()

    def test_prefers_workspace_json_over_subprocess(self, tmp_path, monkeypatch):
        """Cloud Build path: read /workspace/tf_outputs.json instead of running terraform.

        The python:3.13-slim AE deploy steps don't have a terraform binary,
        so subprocess.run() raises FileNotFoundError and silently falls back
        to env vars (which aren't set), producing empty REDIS_ADDR/topics
        that Vertex AI rejects with "Required field is not set". Reading
        the file the read-tf-outputs Cloud Build step already populated
        avoids the broken subprocess path entirely.
        """
        outputs_file = tmp_path / "tf_outputs.json"
        outputs_file.write_text(
            json.dumps(
                {
                    "redis_host": {"value": "10.1.2.3", "type": "string"},
                    "redis_port": {"value": "6379", "type": "string"},
                    "project_id": {"value": "from-file", "type": "string"},
                    "pubsub_topic": {"value": "agent-telemetry", "type": "string"},
                    "agent_engine_sa_email": {
                        "value": "ae@from-file.iam.gserviceaccount.com",
                        "type": "string",
                    },
                }
            )
        )
        monkeypatch.setattr(deploy, "_TF_OUTPUTS_FILE", str(outputs_file))

        called = {"subprocess": False}

        def _explode(*args, **kwargs):
            called["subprocess"] = True
            raise AssertionError("subprocess.run() must NOT be invoked when workspace JSON exists")

        monkeypatch.setattr(deploy.subprocess, "run", _explode)

        result = deploy._read_terraform_outputs()

        assert called["subprocess"] is False
        assert result["redis_host"] == "10.1.2.3"
        assert result["redis_port"] == "6379"
        assert result["project_id"] == "from-file"
        assert result["pubsub_topic"] == "agent-telemetry"
        assert result["agent_engine_sa_email"] == "ae@from-file.iam.gserviceaccount.com"

    def test_falls_back_to_subprocess_when_workspace_json_missing(self, tmp_path, monkeypatch):
        """Local dev path: no /workspace/tf_outputs.json -> shell out to terraform."""
        monkeypatch.setattr(deploy, "_TF_OUTPUTS_FILE", str(tmp_path / "does-not-exist.json"))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps({"redis_host": {"value": "127.0.0.1", "type": "string"}}),
                returncode=0,
            )
            result = deploy._read_terraform_outputs()
            mock_run.assert_called_once()
        assert result["redis_host"] == "127.0.0.1"


# --- _read_requirements ---


class TestReadRequirements:
    def test_reads_pyproject(self, tmp_path, monkeypatch):
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[project]\ndependencies = ["google-adk>=1.0", "requests"]\n')
        monkeypatch.chdir(tmp_path)
        result = deploy._read_requirements()
        assert "google-adk>=1.0" in result
        assert "requests" in result

    def test_returns_empty_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = deploy._read_requirements()
        assert result == []


# --- CLI: --only / --print-url ---


class TestCli:
    """--only filters to a single agent; --print-url emits ONLY the resource URL
    on the final stdout line (Cloud Build captures it via ``| tail -1``)."""

    def test_only_flag_filters_to_single_agent(self, monkeypatch):
        """--only planner deploys planner only, no other agents."""
        deployed: list[str] = []

        def fake_deploy_ae(name, cfg, *, tf, force_create=False):
            deployed.append(name)
            return f"https://us-central1-aiplatform.googleapis.com/v1beta1/projects/test/locations/us-central1/reasoningEngines/{name}-id"

        monkeypatch.setattr(deploy, "deploy_agent_engine", fake_deploy_ae)
        monkeypatch.setattr(deploy, "_read_terraform_outputs", lambda: _make_tf())

        deploy.main(["--only", "planner", "--print-url"])

        assert deployed == ["planner"]

    def test_print_url_emits_url_on_final_stdout_line(self, capsys, monkeypatch):
        """--print-url: the LAST line of stdout must be ONLY the resource URL.

        Cloud Build steps capture this with `... | tail -1` and write it to a
        per-agent .url file. Anything else on the final line breaks AGENT_URLS
        collection.
        """
        sentinel_url = "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/test/locations/us-central1/reasoningEngines/123"
        monkeypatch.setattr(
            deploy,
            "deploy_agent_engine",
            lambda name, cfg, *, tf, force_create=False: sentinel_url,
        )
        monkeypatch.setattr(deploy, "_read_terraform_outputs", lambda: _make_tf())

        deploy.main(["--only", "planner", "--print-url"])

        out_lines = capsys.readouterr().out.strip().splitlines()
        assert out_lines, "expected at least one line of stdout"
        assert out_lines[-1] == sentinel_url

    def test_only_unknown_agent_exits_nonzero(self, monkeypatch):
        """--only with an unknown agent name must exit with a clear error."""
        monkeypatch.setattr(deploy, "_read_terraform_outputs", lambda: _make_tf())
        with pytest.raises(SystemExit) as exc_info:
            deploy.main(["--only", "no-such-agent", "--print-url"])
        assert exc_info.value.code != 0

    def test_only_is_required(self, monkeypatch):
        """deploy.py only supports the --only path; missing it must error out."""
        monkeypatch.setattr(deploy, "_read_terraform_outputs", lambda: _make_tf())
        with pytest.raises(SystemExit) as exc_info:
            deploy.main([])
        assert exc_info.value.code != 0

    def test_only_cloud_run_service_name_rejected(self, monkeypatch):
        """Cloud Run services aren't deployed by deploy.py; rejecting their
        names prevents the orchestrator from accidentally invoking the wrong
        path after the shrink."""
        monkeypatch.setattr(deploy, "_read_terraform_outputs", lambda: _make_tf())
        with pytest.raises(SystemExit) as exc_info:
            deploy.main(["--only", "gateway", "--print-url"])
        assert exc_info.value.code != 0


# --- _resolve_ae_labels (label override via AE_LABELS env var) ---


class TestResolveAELabels:
    def test_default_when_unset(self, monkeypatch):
        """No AE_LABELS env var → returns the canonical OSS demo label."""
        monkeypatch.delenv("AE_LABELS", raising=False)
        assert deploy._resolve_ae_labels() == {"dev-tutorial": "race-condition"}

    def test_default_when_empty(self, monkeypatch):
        """AE_LABELS='' (empty) is treated as unset, not as a missing object."""
        monkeypatch.setenv("AE_LABELS", "")
        assert deploy._resolve_ae_labels() == {"dev-tutorial": "race-condition"}

    def test_env_override_wins(self, monkeypatch):
        """A valid JSON map in AE_LABELS replaces the default entirely."""
        monkeypatch.setenv("AE_LABELS", '{"team":"platform","env":"prod"}')
        assert deploy._resolve_ae_labels() == {"team": "platform", "env": "prod"}

    def test_invalid_json_falls_back_to_default(self, monkeypatch):
        """Malformed AE_LABELS doesn't crash deploy; falls back to the default."""
        monkeypatch.setenv("AE_LABELS", "not-json{{")
        assert deploy._resolve_ae_labels() == {"dev-tutorial": "race-condition"}

    def test_non_dict_json_falls_back_to_default(self, monkeypatch):
        """AE_LABELS must be an object; arrays / strings / numbers fall back."""
        monkeypatch.setenv("AE_LABELS", '["dev-tutorial","race-condition"]')
        assert deploy._resolve_ae_labels() == {"dev-tutorial": "race-condition"}

    def test_values_coerced_to_strings(self, monkeypatch):
        """GCP labels must be strings; coerce numeric / boolean inputs."""
        monkeypatch.setenv("AE_LABELS", '{"version": 7, "active": true}')
        assert deploy._resolve_ae_labels() == {"version": "7", "active": "True"}


# --- _apply_labels_to_engine (REST PATCH that the SDK can't do) ---


class TestApplyLabelsToEngine:
    def test_no_op_on_empty_labels(self, monkeypatch):
        """Empty labels dict → no HTTP call (avoids surprise PATCH)."""
        called = []
        monkeypatch.setattr(deploy.requests, "patch", lambda *a, **kw: called.append((a, kw)))
        deploy._apply_labels_to_engine("projects/p/locations/us-central1/reasoningEngines/1", "us-central1", {})
        assert called == []

    def test_patches_with_correct_url_and_payload(self, monkeypatch):
        """PATCH targets the AE resource with updateMask=labels and the labels in body."""
        captured = {}

        def fake_patch(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "{}"
            return resp

        fake_creds = MagicMock(token="fake-token")
        monkeypatch.setattr(deploy.google.auth, "default", lambda: (fake_creds, None))
        monkeypatch.setattr(deploy.requests, "patch", fake_patch)

        deploy._apply_labels_to_engine(
            "projects/p/locations/us-central1/reasoningEngines/1234",
            "us-central1",
            {"dev-tutorial": "race-condition"},
        )

        assert captured["url"] == (
            "https://aiplatform.googleapis.com/v1beta1/"
            "projects/p/locations/us-central1/reasoningEngines/1234?updateMask=labels"
        )
        assert captured["json"] == {"labels": {"dev-tutorial": "race-condition"}}
        assert captured["headers"]["Authorization"] == "Bearer fake-token"

    def test_uses_regional_endpoint_for_non_us_central1(self, monkeypatch):
        """europe-west4 → europe-west4-aiplatform.googleapis.com (Vertex regional endpoint convention)."""
        captured = {}

        def fake_patch(url, **kw):
            captured["url"] = url
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "{}"
            return resp

        monkeypatch.setattr(deploy.google.auth, "default", lambda: (MagicMock(token="t"), None))
        monkeypatch.setattr(deploy.requests, "patch", fake_patch)

        deploy._apply_labels_to_engine(
            "projects/p/locations/europe-west4/reasoningEngines/1",
            "europe-west4",
            {"dev-tutorial": "race-condition"},
        )

        assert captured["url"].startswith("https://europe-west4-aiplatform.googleapis.com/")

    def test_failure_is_non_fatal(self, monkeypatch):
        """Network exception during PATCH must NOT abort the deploy."""

        def boom(*a, **kw):
            raise ConnectionError("simulated network failure")

        monkeypatch.setattr(deploy.google.auth, "default", lambda: (MagicMock(token="t"), None))
        monkeypatch.setattr(deploy.requests, "patch", boom)

        # Should return without raising.
        deploy._apply_labels_to_engine(
            "projects/p/locations/us-central1/reasoningEngines/1",
            "us-central1",
            {"dev-tutorial": "race-condition"},
        )

    def test_4xx_response_is_non_fatal(self, monkeypatch):
        """A non-2xx HTTP response is logged but doesn't raise."""

        def fake_patch(*a, **kw):
            resp = MagicMock()
            resp.status_code = 403
            resp.text = "permission denied"
            return resp

        monkeypatch.setattr(deploy.google.auth, "default", lambda: (MagicMock(token="t"), None))
        monkeypatch.setattr(deploy.requests, "patch", fake_patch)

        # Should return cleanly.
        deploy._apply_labels_to_engine(
            "projects/p/locations/us-central1/reasoningEngines/1",
            "us-central1",
            {"dev-tutorial": "race-condition"},
        )
