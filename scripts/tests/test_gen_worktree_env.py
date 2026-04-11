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

"""Tests for gen_worktree_env.py -- port offset generation for worktrees."""

import os
import tempfile

import pytest


class TestApplyOffset:
    """Tests for the apply_offset function."""

    def test_slot_zero_no_change(self):
        from scripts.core.gen_worktree_env import apply_offset

        assert apply_offset(8000, 0) == 8000

    def test_slot_one_adds_1000(self):
        from scripts.core.gen_worktree_env import apply_offset

        assert apply_offset(8000, 1) == 9000

    def test_slot_three_adds_3000(self):
        from scripts.core.gen_worktree_env import apply_offset

        assert apply_offset(8101, 3) == 11101

    def test_rejects_negative_slot(self):
        from scripts.core.gen_worktree_env import apply_offset

        with pytest.raises(ValueError, match="Slot must be between 0 and 3"):
            apply_offset(8000, -1)

    def test_rejects_slot_above_max(self):
        from scripts.core.gen_worktree_env import apply_offset

        with pytest.raises(ValueError, match="Slot must be between 0 and 3"):
            apply_offset(8000, 4)


class TestTransformEnvLine:
    """Tests for transforming individual .env lines."""

    def test_port_variable_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("GATEWAY_PORT=8101", 1)
        assert result == "GATEWAY_PORT=9101"

    def test_addr_variable_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("GATEWAY_ADDR=127.0.0.1:8101", 1)
        assert result == "GATEWAY_ADDR=127.0.0.1:9101"

    def test_url_variable_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("SIMULATOR_URL=http://127.0.0.1:8202", 1)
        assert result == "SIMULATOR_URL=http://127.0.0.1:9202"

    def test_ws_url_variable_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("VITE_GATEWAY_URL=ws://127.0.0.1:8101/ws", 1)
        assert result == "VITE_GATEWAY_URL=ws://127.0.0.1:9101/ws"

    def test_redis_addr_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("REDIS_ADDR=127.0.0.1:8102", 2)
        assert result == "REDIS_ADDR=127.0.0.1:10102"

    def test_pubsub_host_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("PUBSUB_EMULATOR_HOST=127.0.0.1:8103", 2)
        assert result == "PUBSUB_EMULATOR_HOST=127.0.0.1:10103"

    def test_agent_urls_all_ports_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        line = "AGENT_URLS=http://127.0.0.1:8202,http://127.0.0.1:8204"
        result = transform_env_line(line, 1)
        assert result == "AGENT_URLS=http://127.0.0.1:9202,http://127.0.0.1:9204"

    def test_comment_lines_unchanged(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("# --- Simulation Ports ---", 1)
        assert result == "# --- Simulation Ports ---"

    def test_empty_line_unchanged(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("", 1)
        assert result == ""

    def test_non_port_variable_unchanged(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("PROJECT_ID=n26-devkey-simulation-dev", 1)
        assert result == "PROJECT_ID=n26-devkey-simulation-dev"

    def test_gcp_config_unchanged(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("GOOGLE_CLOUD_LOCATION=global", 1)
        assert result == "GOOGLE_CLOUD_LOCATION=global"

    def test_frontend_app_url_gets_offset(self):
        from scripts.core.gen_worktree_env import transform_env_line

        result = transform_env_line("FRONTEND_APP_URL=http://127.0.0.1:8501", 1)
        assert result == "FRONTEND_APP_URL=http://127.0.0.1:9501"

    def test_slot_zero_leaves_everything_unchanged(self):
        from scripts.core.gen_worktree_env import transform_env_line

        assert transform_env_line("GATEWAY_PORT=8101", 0) == "GATEWAY_PORT=8101"
        assert transform_env_line("GATEWAY_ADDR=127.0.0.1:8101", 0) == "GATEWAY_ADDR=127.0.0.1:8101"
        assert transform_env_line("SIMULATOR_URL=http://127.0.0.1:8202", 0) == "SIMULATOR_URL=http://127.0.0.1:8202"


class TestGenerateEnv:
    """Tests for the full .env file generation."""

    def test_generates_env_file_from_template(self):
        from scripts.core.gen_worktree_env import generate_env

        template = "# Ports\nGATEWAY_PORT=8101\nGATEWAY_ADDR=127.0.0.1:8101\nPROJECT_ID=test\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, ".env.example")
            output_path = os.path.join(tmpdir, ".env")

            with open(template_path, "w") as f:
                f.write(template)

            generate_env(template_path, output_path, slot=1)

            with open(output_path) as f:
                content = f.read()

            assert "GATEWAY_PORT=9101" in content
            assert "GATEWAY_ADDR=127.0.0.1:9101" in content
            assert "PROJECT_ID=test" in content

    def test_writes_port_slot_marker(self):
        from scripts.core.gen_worktree_env import generate_env

        template = "GATEWAY_PORT=8101\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, ".env.example")
            output_path = os.path.join(tmpdir, ".env")
            slot_path = os.path.join(tmpdir, ".port-slot")

            with open(template_path, "w") as f:
                f.write(template)

            generate_env(template_path, output_path, slot=2, slot_marker_path=slot_path)

            with open(slot_path) as f:
                assert f.read().strip() == "2"


class TestGenerateDockerComposeOverride:
    """Tests for docker-compose.override.yml generation."""

    def test_slot_zero_does_not_create_override(self):
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=0)
            assert not os.path.exists(override_path)

    def test_slot_one_creates_override_with_offset_ports(self):
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=1)

            with open(override_path) as f:
                content = f.read()

            # Redis: 9102:6379 (8102 + 1000)
            assert "9102:6379" in content
            # PubSub: 9103:8085 (8103 + 1000)
            assert "9103:8085" in content

    def test_slot_two_creates_override_with_offset_ports(self):
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=2)

            with open(override_path) as f:
                content = f.read()

            assert "10102:6379" in content
            assert "10103:8085" in content

    def test_override_has_unique_container_names(self):
        """Each slot needs unique container names to avoid conflicts."""
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=2)

            with open(override_path) as f:
                content = f.read()

            # Container names should include the slot number
            assert "redis-slot-2" in content
            assert "pubsub-slot-2" in content

    def test_override_is_standalone_with_full_service_defs(self):
        """Override must be standalone (not a merge) to avoid port list appending."""
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=1)

            with open(override_path) as f:
                content = f.read()

            # Must include full image definitions (standalone, not merge override)
            assert "image: redis:7-alpine" in content
            assert "image: gcr.io/google.com/cloudsdktool/cloud-sdk:latest" in content
            # Must include healthcheck
            assert "healthcheck" in content
            # Must include environment for pubsub
            assert "PUBSUB_PROJECT_ID=test-project" in content

    def test_override_disables_redis_rdb_persistence(self):
        """Redis must disable RDB snapshots to avoid MISCONF write errors."""
        from scripts.core.gen_worktree_env import generate_docker_compose_override

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = os.path.join(tmpdir, "docker-compose.override.yml")
            generate_docker_compose_override(override_path, slot=1)

            with open(override_path) as f:
                content = f.read()

            # Must disable RDB snapshots (--save "") to prevent MISCONF errors
            assert '--save ""' in content or "--save ''" in content, (
                "Redis command must include --save '' to disable RDB persistence"
            )


class TestDockerComposeBaseRedisConfig:
    """Tests for docker-compose.yml base Redis hardening."""

    def test_base_compose_disables_rdb_persistence(self):
        """Base docker-compose.yml must disable Redis RDB snapshots."""
        # Go up three levels: tests/ -> scripts/ -> repo root
        compose_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "docker-compose.yml",
        )
        with open(compose_path) as f:
            content = f.read()

        assert '--save ""' in content or "--save ''" in content, (
            "docker-compose.yml redis command must include --save '' to prevent MISCONF RDB snapshot errors"
        )
