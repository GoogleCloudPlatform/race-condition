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

"""Tests for pre-race skill tools."""

import importlib.util
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Dynamic import since the skill directory is hyphenated
tools_path = pathlib.Path(__file__).parents[1] / "skills" / "pre-race" / "tools.py"
spec = importlib.util.spec_from_file_location("pre_race.tools", tools_path)
assert spec is not None, f"Could not find module spec for {tools_path}"
assert spec.loader is not None, f"Module spec has no loader for {tools_path}"
tools_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools_module)

prepare_simulation = tools_module.prepare_simulation
spawn_runners = tools_module.spawn_runners
start_race_collector = tools_module.start_race_collector
call_agent = tools_module.call_agent
fire_start_gun = tools_module.fire_start_gun


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Create a mock ToolContext with a mutable state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-session-1"
    ctx.invocation_id = "inv-001"
    ctx.agent_name = "simulator"
    return ctx


# ---------------------------------------------------------------------------
# TestPrepareSimulation
# ---------------------------------------------------------------------------
class TestPrepareSimulation:
    """Tests for the prepare_simulation tool."""

    @pytest.mark.asyncio
    async def test_computes_max_ticks(self):
        """120s / 5s tick interval = 24 max ticks."""
        plan = {
            "action": "start",
            "narrative": "A great race",
            "route": {"type": "FeatureCollection"},
            "simulation_config": {"duration_seconds": 120, "tick_interval_seconds": 5},
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert result["max_ticks"] == 24

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        """Default duration=120, tick_interval=10 when no simulation_config provided."""
        plan = {"action": "start", "narrative": "Test narrative", "route": {"type": "FeatureCollection"}}
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert result["max_ticks"] == 12  # 120 / 10
        assert result["duration_seconds"] == 120
        assert result["tick_interval_seconds"] == 10

    @pytest.mark.asyncio
    async def test_default_runner_count_matches_cap_for_default_runner_type(self, monkeypatch):
        """When the plan omits runner_count, it defaults to the per-type cap.

        The default runner_type is runner_autopilot, so the default count is
        MAX_RUNNERS_AUTOPILOT (which is 100 in OSS GCP defaults). This matches
        the user-facing expectation: a single runner-autopilot Cloud Run
        instance handles 100 simulated runners. Local dev can dial it down via
        env var; the planner can always override with an explicit runner_count.
        """
        monkeypatch.setenv("MAX_RUNNERS_AUTOPILOT", "100")
        plan = {"action": "start", "narrative": "Test", "route": {}}
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert result["runner_count"] == 100
        assert ctx.state["runner_count"] == 100
        assert ctx.state["simulation_config"]["runner_count"] == 100
        assert ctx.state["simulation_config"]["runner_type"] == "runner_autopilot"

    @pytest.mark.asyncio
    async def test_reads_simulation_config_from_plan(self, monkeypatch):
        """simulation_config in plan JSON overrides defaults."""
        # This test asserts config values are read; grant cap headroom so the
        # per-type clamp doesn't interfere with the runner_count=500 fixture.
        monkeypatch.setenv("MAX_RUNNERS_AUTOPILOT", "1000")
        plan = {
            "action": "execute",
            "narrative": "Custom config",
            "route": {"type": "FeatureCollection"},
            "simulation_config": {
                "duration_seconds": 60,
                "tick_interval_seconds": 10,
                "total_race_hours": 3.0,
                "runner_count": 500,
            },
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert result["max_ticks"] == 6  # 60 / 10
        assert result["runner_count"] == 500
        assert ctx.state["simulation_config"]["total_race_hours"] == 3.0
        assert ctx.state["simulation_config"]["runner_count"] == 500
        assert ctx.state["runner_count"] == 500

    @pytest.mark.asyncio
    async def test_stores_route_in_state(self):
        """Route from the plan should be stored in tool_context.state['route_geojson']."""
        route_data = {"type": "FeatureCollection", "features": []}
        plan = {"action": "start", "narrative": "Narrative", "route": route_data}
        ctx = _make_tool_context()

        await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert ctx.state["route_geojson"] == route_data
        assert ctx.state["max_ticks"] == 12  # default 120s / 10s
        assert ctx.state["simulation_config"]["tick_interval_seconds"] == 10

    @pytest.mark.asyncio
    async def test_sets_simulation_ready_flag(self):
        """prepare_simulation should set simulation_ready=True in state."""
        plan = {"action": "execute", "narrative": "Test", "route": {}}
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert ctx.state["simulation_ready"] is True

    @pytest.mark.asyncio
    async def test_initializes_tick_state(self):
        """prepare_simulation should initialize current_tick=0 and tick_snapshots=[]."""
        plan = {"action": "execute", "narrative": "Test", "route": {}}
        ctx = _make_tool_context()

        await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert ctx.state["current_tick"] == 0
        assert ctx.state["tick_snapshots"] == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        """Invalid JSON should return an error status."""
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json="not-valid-json",
            tool_context=ctx,
        )

        assert result["status"] == "error"
        # simulation_ready should NOT be set on error
        assert "simulation_ready" not in ctx.state

    @pytest.mark.asyncio
    async def test_runner_type_from_config(self):
        """runner_type from simulation_config should be used when provided."""
        plan = {
            "action": "execute",
            "narrative": "Runner type test",
            "route": {"type": "FeatureCollection"},
            "simulation_config": {"runner_type": "runner_cloudrun"},
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(
            plan_json=json.dumps(plan),
            tool_context=ctx,
        )

        assert result["status"] == "success"
        assert ctx.state["runner_type"] == "runner_cloudrun"
        assert ctx.state["simulation_config"]["runner_type"] == "runner_cloudrun"

    @pytest.mark.asyncio
    async def test_runner_type_defaults_to_runner_autopilot(self):
        """runner_type should always be 'runner_autopilot' even without config."""
        plan = {"action": "execute", "narrative": "Test", "route": {}}
        ctx = _make_tool_context()

        await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert ctx.state["runner_type"] == "runner_autopilot"

    @pytest.mark.asyncio
    async def test_runner_type_from_config_ignores_env_var(self):
        """runner_type from config is used; env var is ignored."""
        plan = {
            "action": "execute",
            "narrative": "Test",
            "route": {},
            "simulation_config": {"runner_type": "runner_gke"},
        }
        ctx = _make_tool_context()

        with patch.dict("os.environ", {"RUNNER_AGENT_TYPE": "something_else"}):
            await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert ctx.state["runner_type"] == "runner_gke"

    @pytest.mark.asyncio
    async def test_prepare_simulation_preserves_existing_simulation_id(self):
        """When state already has simulation_id (set by root callback),
        prepare_simulation must NOT overwrite it with session.id."""
        plan = {"action": "execute", "narrative": "Test", "route": {}}
        ctx = _make_tool_context()
        ctx.session.id = "pipeline-session-xyz"
        # Root callback already set this:
        ctx.state["simulation_id"] = "root-session-abc"

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"
        # Must preserve root's simulation_id, NOT overwrite with pipeline's session.id
        assert ctx.state["simulation_id"] == "root-session-abc"
        assert result["simulation_id"] == "root-session-abc"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "runner_type, env_var, env_value, requested, expected",
        [
            # Autopilot honours MAX_RUNNERS_AUTOPILOT
            ("runner_autopilot", "MAX_RUNNERS_AUTOPILOT", "100", 5000, 100),
            ("runner_autopilot", "MAX_RUNNERS_AUTOPILOT", "100", 100, 100),
            ("runner_autopilot", "MAX_RUNNERS_AUTOPILOT", "100", 50, 50),
            # LLM types honour MAX_RUNNERS_LLM
            ("runner", "MAX_RUNNERS_LLM", "10", 100, 10),
            ("runner_cloudrun", "MAX_RUNNERS_LLM", "10", 100, 10),
            ("runner_gke", "MAX_RUNNERS_LLM", "10", 100, 10),
            ("runner", "MAX_RUNNERS_LLM", "10", 10, 10),
            ("runner", "MAX_RUNNERS_LLM", "10", 5, 5),
            # GCP-style values honoured
            ("runner_autopilot", "MAX_RUNNERS_AUTOPILOT", "1000", 5000, 1000),
            ("runner", "MAX_RUNNERS_LLM", "100", 5000, 100),
        ],
    )
    async def test_runner_count_capped_per_type(
        self, monkeypatch, runner_type, env_var, env_value, requested, expected
    ):
        """prepare_simulation clamps runner_count using the per-type env var cap."""
        monkeypatch.setenv(env_var, env_value)
        ctx = _make_tool_context(state={"simulation_id": "sim-cap-test"})
        plan_json = json.dumps(
            {
                "action": "execute",
                "narrative": "test",
                "route": {},
                "simulation_config": {
                    "runner_count": requested,
                    "runner_type": runner_type,
                },
            }
        )
        result = await prepare_simulation(plan_json=plan_json, tool_context=ctx)

        assert result["status"] == "success"
        assert result["runner_count"] == expected
        assert ctx.state["runner_count"] == expected
        assert ctx.state["simulation_config"]["runner_count"] == expected
        # Preserve original coverage: capped_from telemetry only present when clamped.
        if requested > expected:
            assert result["capped_from"] == requested
        else:
            assert "capped_from" not in result

    @pytest.mark.asyncio
    async def test_capped_from_telemetry_includes_requested_value(self, monkeypatch):
        """When clamped, result.capped_from carries the original requested value."""
        monkeypatch.setenv("MAX_RUNNERS_LLM", "10")
        ctx = _make_tool_context(state={"simulation_id": "sim-tele"})
        plan_json = json.dumps(
            {
                "action": "execute",
                "narrative": "test",
                "route": {},
                "simulation_config": {"runner_count": 500, "runner_type": "runner"},
            }
        )
        result = await prepare_simulation(plan_json=plan_json, tool_context=ctx)

        assert result["runner_count"] == 10
        assert result["capped_from"] == 500
        assert "10" in result["message"]  # mentions clamped value
        assert "500" in result["message"]  # mentions original


# ---------------------------------------------------------------------------
# TestRootCallback
# ---------------------------------------------------------------------------
class TestRootCallback:
    """Tests for _capture_root_simulation_id callback."""

    @pytest.mark.asyncio
    async def test_root_callback_captures_session_id(self):
        """_capture_root_simulation_id sets state['simulation_id'] from session.id.

        On local (no registry mapping), falls back to session.id directly.
        """
        from agents.simulator.agent import _capture_root_simulation_id

        ctx = MagicMock()
        ctx.session.id = "root-session-999"
        ctx.state = {}

        result = await _capture_root_simulation_id(ctx)

        assert ctx.state["simulation_id"] == "root-session-999"
        assert result is None

    @pytest.mark.asyncio
    async def test_root_callback_does_not_overwrite(self):
        """If simulation_id is already in state, the callback doesn't overwrite it."""
        from agents.simulator.agent import _capture_root_simulation_id

        ctx = MagicMock()
        ctx.session.id = "new-session-id"
        ctx.state = {"simulation_id": "existing-id"}

        result = await _capture_root_simulation_id(ctx)

        assert ctx.state["simulation_id"] == "existing-id"
        assert result is None

    @pytest.mark.asyncio
    async def test_root_callback_uses_registry_on_ae(self):
        """On Agent Engine, get_context_id maps Vertex ID back to spawn UUID."""
        from agents.simulator.agent import _capture_root_simulation_id
        from agents.utils import simulation_registry

        # Simulate AE: register a context mapping (vertex ID → spawn UUID)
        await simulation_registry.register_context("40765115", "planner-uuid-abc")

        ctx = MagicMock()
        ctx.session.id = "40765115"  # Vertex-generated ID
        ctx.state = {}

        result = await _capture_root_simulation_id(ctx)

        # Should use the original spawn UUID, not the Vertex ID
        assert ctx.state["simulation_id"] == "planner-uuid-abc"
        assert result is None

        # Cleanup
        simulation_registry._context_map.clear()


# ---------------------------------------------------------------------------
# TestSpawnRunners
# ---------------------------------------------------------------------------
class TestSpawnRunners:
    """Tests for the spawn_runners tool."""

    @staticmethod
    def _make_aiohttp_mocks(response_status, response_data):
        """Create properly nested aiohttp mock for async with session.post(...) pattern."""
        mock_response = MagicMock()
        mock_response.status = response_status
        if response_status == 200:
            mock_response.json = AsyncMock(return_value=response_data)
        else:
            mock_response.text = AsyncMock(return_value=response_data)

        # response is used as async context manager: async with session.post() as resp
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        # session.post() returns the context manager directly (not a coroutine)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)

        # session itself is used as async context manager: async with ClientSession() as session
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        return mock_session, mock_response

    @pytest.mark.asyncio
    async def test_calls_gateway_spawn_api(self):
        """spawn_runners should POST to {GATEWAY_URL}/api/v1/spawn."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {
                "sessions": [
                    {"sessionId": "runner-1", "agentType": "runner_autopilot"},
                    {"sessionId": "runner-2", "agentType": "runner_autopilot"},
                    {"sessionId": "runner-3", "agentType": "runner_autopilot"},
                ]
            },
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"GATEWAY_URL": "http://test-gateway:8101"}):
                result = await spawn_runners(count=3, tool_context=ctx)

        assert result["status"] == "success"
        assert result["session_ids"] == ["runner-1", "runner-2", "runner-3"]

        # Verify the POST was called with correct URL and payload
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "http://test-gateway:8101/api/v1/spawn"
        posted_json = call_args[1]["json"]
        assert posted_json["agents"] == [{"agentType": "runner_autopilot", "count": 3}]
        assert "simulation_id" in posted_json

    @pytest.mark.asyncio
    async def test_stores_session_ids_in_state(self):
        """Session IDs from spawn response should be stored in state."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {
                "sessions": [
                    {"sessionId": "r-a", "agentType": "runner_autopilot"},
                    {"sessionId": "r-b", "agentType": "runner_autopilot"},
                ]
            },
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await spawn_runners(count=2, tool_context=ctx)

        assert ctx.state["runner_session_ids"] == ["r-a", "r-b"]

    @pytest.mark.asyncio
    async def test_spawn_http_error_returns_error(self):
        """Non-200 response should return error status."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(500, "Internal Server Error")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await spawn_runners(count=3, tool_context=ctx)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_attaches_oidc_token_when_audience_resolves(self):
        """In OSS Cloud Run IAM mode, spawn_runners must attach Authorization: Bearer."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200, {"sessions": [{"sessionId": "r1", "agentType": "runner_autopilot"}]}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch(
                "agents.utils.auth.get_id_token",
                return_value="eyJfaketoken",
            ):
                with patch.dict(
                    "os.environ",
                    {"GATEWAY_INTERNAL_URL": "https://gateway.run.app"},
                ):
                    await spawn_runners(count=1, tool_context=ctx)

        # session.post(spawn_url, json=payload, headers={...}) — assert the headers kwarg.
        call_args = mock_session.post.call_args
        headers = call_args[1].get("headers") or {}
        assert headers.get("Authorization") == "Bearer eyJfaketoken", (
            f"Expected Authorization Bearer header, got {headers!r}"
        )

    @pytest.mark.asyncio
    async def test_omits_authorization_when_token_unavailable(self):
        """When get_id_token returns None (local dev / no ADC), no Authorization header."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200, {"sessions": [{"sessionId": "r1", "agentType": "runner_autopilot"}]}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("agents.utils.auth.get_id_token", return_value=None):
                with patch.dict("os.environ", {"GATEWAY_URL": "http://localhost:8101"}, clear=False):
                    await spawn_runners(count=1, tool_context=ctx)

        call_args = mock_session.post.call_args
        headers = call_args[1].get("headers") or {}
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_uses_runner_type_from_state(self):
        """spawn_runners should use runner_type from state for agentType."""
        ctx = _make_tool_context(state={"runner_type": "runner_autopilot", "simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": "r-1", "agentType": "runner_autopilot"}]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"GATEWAY_URL": "http://test-gateway:8101"}):
                result = await spawn_runners(count=1, tool_context=ctx)

        assert result["status"] == "success"
        posted_json = mock_session.post.call_args[1]["json"]
        assert posted_json["agents"] == [{"agentType": "runner_autopilot", "count": 1}]
        assert "simulation_id" in posted_json

    @pytest.mark.asyncio
    async def test_prefers_internal_gateway_url(self):
        """spawn_runners should prefer GATEWAY_INTERNAL_URL over GATEWAY_URL."""
        ctx = _make_tool_context(state={"simulation_ready": True})
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": "r-1", "agentType": "runner_autopilot"}]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict(
                "os.environ",
                {
                    "GATEWAY_INTERNAL_URL": "https://gateway-internal.run.app",
                    "GATEWAY_URL": "https://gateway.public.example.com",
                },
            ):
                result = await spawn_runners(count=1, tool_context=ctx)

        assert result["status"] == "success"
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://gateway-internal.run.app/api/v1/spawn"

    @pytest.mark.asyncio
    async def test_defaults_to_runner_autopilot_without_state(self):
        """spawn_runners should default to 'runner_autopilot' when runner_type not in state."""
        ctx = _make_tool_context(state={"simulation_ready": True})  # no runner_type in state
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": "r-1", "agentType": "runner_autopilot"}]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await spawn_runners(count=1, tool_context=ctx)

        assert result["status"] == "success"
        posted_json = mock_session.post.call_args[1]["json"]
        assert posted_json["agents"] == [{"agentType": "runner_autopilot", "count": 1}]
        assert "simulation_id" in posted_json

    @pytest.mark.asyncio
    async def test_includes_simulation_id_in_spawn_request(self):
        """spawn_runners should include simulation_id from state in the spawn payload."""
        ctx = _make_tool_context(
            state={"simulation_id": "sim-xyz-789", "runner_type": "runner_autopilot", "simulation_ready": True}
        )
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": "r-1", "agentType": "runner_autopilot"}]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"GATEWAY_URL": "http://test-gateway:8101"}):
                result = await spawn_runners(count=1, tool_context=ctx)

        assert result["status"] == "success"
        posted_json = mock_session.post.call_args[1]["json"]
        assert posted_json["simulation_id"] == "sim-xyz-789"

    @pytest.mark.asyncio
    async def test_spawn_without_simulation_id_sends_empty_string(self):
        """spawn_runners should send empty simulation_id when not in state."""
        ctx = _make_tool_context(state={"simulation_ready": True})  # no simulation_id
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": "r-1", "agentType": "runner_autopilot"}]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await spawn_runners(count=1, tool_context=ctx)

        assert result["status"] == "success"
        posted_json = mock_session.post.call_args[1]["json"]
        assert posted_json["simulation_id"] == ""

    @pytest.mark.asyncio
    async def test_spawn_runners_returns_simulation_id(self):
        """spawn_runners should include simulation_id in success response."""
        ctx = _make_tool_context(
            state={
                "runner_type": "runner_autopilot",
                "simulation_id": "sim-77",
                "simulation_ready": True,
            }
        )
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"sessions": [{"sessionId": "r-1"}]})
        mock_response.text = AsyncMock(return_value="")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await spawn_runners(1, ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_reconciles_runner_count_with_actual_spawned(self):
        """When gateway caps spawn count below runner_count, state must be reconciled."""
        ctx = _make_tool_context(
            state={
                "simulation_ready": True,
                "runner_count": 1000,
                "simulation_config": {"runner_count": 1000},
            }
        )
        # Gateway only returns 100 runners (its own MAX_RUNNERS cap)
        mock_session, _ = self._make_aiohttp_mocks(
            200,
            {"sessions": [{"sessionId": f"r-{i}", "agentType": "runner_autopilot"} for i in range(100)]},
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await spawn_runners(count=1000, tool_context=ctx)

        assert result["status"] == "success"
        assert result["count"] == 100
        # State must reflect actual spawned count, not requested
        assert ctx.state["runner_count"] == 100
        assert ctx.state["simulation_config"]["runner_count"] == 100


# ---------------------------------------------------------------------------
# TestStartRaceCollector
# ---------------------------------------------------------------------------
class TestStartRaceCollector:
    """Tests for the start_race_collector tool."""

    @pytest.mark.asyncio
    async def test_starts_collector(self):
        """start_race_collector should instantiate and start a RaceCollector."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1", "r-2"], "simulation_ready": True})
        mock_collector = AsyncMock()

        with patch("agents.simulator.collector.RaceCollector.start", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = mock_collector

            result = await start_race_collector(tool_context=ctx)

        assert result["status"] == "success"
        mock_start.assert_called_once()
        # Verify session_id and runner_session_ids were passed
        call_kwargs = mock_start.call_args
        assert call_kwargs[1]["session_id"] == "sim-session-1"
        assert call_kwargs[1]["runner_session_ids"] == {"r-1", "r-2"}

    @pytest.mark.asyncio
    async def test_no_redis_url_parameter(self):
        """start_race_collector must NOT pass redis_url -- the shared pool handles it."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1"], "simulation_ready": True})

        with patch("agents.simulator.collector.RaceCollector.start", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = AsyncMock()
            result = await start_race_collector(tool_context=ctx)

        assert result["status"] == "success"
        call_kwargs = mock_start.call_args
        assert "redis_url" not in (call_kwargs[1] if call_kwargs[1] else {}), (
            "redis_url should not be passed -- the shared pool handles Redis connections"
        )

    @pytest.mark.asyncio
    async def test_collector_missing_runner_ids_returns_error(self):
        """If runner_session_ids not in state, should return error."""
        ctx = _make_tool_context(state={"simulation_ready": True})

        result = await start_race_collector(tool_context=ctx)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_start_race_collector_returns_simulation_id(self):
        """start_race_collector should include simulation_id in success response."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1"],
                "simulation_id": "sim-77",
                "simulation_ready": True,
            }
        )
        with patch("agents.simulator.collector.RaceCollector.start", new_callable=AsyncMock):
            result = await start_race_collector(ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"


# ---------------------------------------------------------------------------
# TestFireStartGun
# ---------------------------------------------------------------------------
class TestFireStartGun:
    """Tests for the fire_start_gun tool."""

    @pytest.mark.asyncio
    async def test_broadcasts_start_gun_event(self):
        """fire_start_gun should broadcast a START_GUN signal without tick data."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1", "r-2"]})

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock) as mock_publish:
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_publish.assert_called_once()
        published = json.loads(mock_publish.call_args_list[0][0][0])
        assert published["event"] == "start_gun"
        assert "session_id" not in published
        # START_GUN no longer contains tick data -- init is deferred to tick 0
        assert "tick" not in published
        assert "minutes_per_tick" not in published
        assert "elapsed_minutes" not in published

    @pytest.mark.asyncio
    async def test_returns_error_without_runners(self):
        """fire_start_gun should return error if no runners have been spawned."""
        ctx = _make_tool_context(state={})

        result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_handles_broadcast_failure(self):
        """fire_start_gun should handle publish errors gracefully."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1"]})

        with patch.object(
            tools_module,
            "publish_to_runners",
            new_callable=AsyncMock,
            side_effect=Exception("Redis down"),
        ):
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_passes_simulation_id_to_broadcast(self):
        """fire_start_gun should pass simulation_id from state to publish_to_runners."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1", "r-2"],
                "simulation_id": "sim-fire-123",
            }
        )

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock) as mock_publish:
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args
        assert call_kwargs[1].get("simulation_id") == "sim-fire-123" or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "sim-fire-123"
        )

    @pytest.mark.asyncio
    async def test_fire_start_gun_returns_simulation_id(self):
        """fire_start_gun should include simulation_id in success response."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1"],
                "simulation_id": "sim-77",
            }
        )
        with patch.object(tools_module, "publish_to_runners", AsyncMock()):
            result = await fire_start_gun(ctx)
        assert result["status"] == "success"
        assert result["simulation_id"] == "sim-77"

    @pytest.mark.asyncio
    async def test_auto_starts_collector_if_not_running(self):
        """fire_start_gun should start the RaceCollector if not already running."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1", "r-2", "r-3"]})

        mock_start = AsyncMock(return_value=MagicMock())
        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch(
                "agents.simulator.collector.RaceCollector.start",
                mock_start,
            ),
        ):
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_start.assert_called_once_with(
            session_id="sim-session-1",
            runner_session_ids={"r-1", "r-2", "r-3"},
        )

    @pytest.mark.asyncio
    async def test_skips_collector_start_if_already_running(self):
        """fire_start_gun should NOT restart the collector if already active."""
        ctx = _make_tool_context(state={"runner_session_ids": ["r-1"]})

        mock_start = AsyncMock()
        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch(
                "agents.simulator.collector.RaceCollector.is_running",
                return_value=True,
            ),
            patch(
                "agents.simulator.collector.RaceCollector.start",
                mock_start,
            ),
        ):
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_start.assert_not_called()

    # --- Instant Start Velocity: TICK-0 broadcast tests ---

    @pytest.mark.asyncio
    async def test_start_gun_contains_race_metadata(self):
        """fire_start_gun should include max_ticks and race_distance in the event."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1", "r-2"],
                "simulation_config": {
                    "total_race_hours": 6.0,
                    "tick_interval_seconds": 5,
                },
                "max_ticks": 12,
                "current_tick": 0,
            }
        )

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock) as mock_publish:
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_publish.assert_called_once()

        payload = json.loads(mock_publish.call_args_list[0][0][0])
        assert payload["event"] == "start_gun"
        assert payload["max_ticks"] == 12
        assert payload["race_distance_mi"] == 26.2188

    @pytest.mark.asyncio
    async def test_initializes_current_tick_to_zero(self):
        """After fire_start_gun, current_tick should be 0 (advance_tick starts here).

        The START_GUN is a separate initialization event. Real ticks start
        at 0 via advance_tick so that 60s/5s = 12 ticks produces exactly
        12 tick_snapshots.
        """
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1"],
                "simulation_config": {
                    "total_race_hours": 6.0,
                    "tick_interval_seconds": 5,
                },
                "max_ticks": 12,
            }
        )

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock):
            await fire_start_gun(tool_context=ctx)

        assert ctx.state["current_tick"] == 0

    @pytest.mark.asyncio
    async def test_start_gun_has_no_tick_timing_data(self):
        """START_GUN should NOT contain tick timing data -- that's tick 0's job."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1"],
                "simulation_config": {
                    "total_race_hours": 6.0,
                    "tick_interval_seconds": 5,
                },
                "max_ticks": 12,
                "current_tick": 0,
            }
        )

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock) as mock_publish:
            await fire_start_gun(tool_context=ctx)

        mock_publish.assert_called_once()
        payload = json.loads(mock_publish.call_args_list[0][0][0])
        # No tick timing data in START_GUN event
        assert "minutes_per_tick" not in payload
        assert "elapsed_minutes" not in payload
        assert "tick" not in payload

    @pytest.mark.asyncio
    async def test_start_gun_uses_defaults_when_config_missing(self):
        """START_GUN should use defaults when simulation_config is missing."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1"],
                # No simulation_config, max_ticks defaults
            }
        )

        with patch.object(tools_module, "publish_to_runners", new_callable=AsyncMock) as mock_publish:
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        mock_publish.assert_called_once()

        payload = json.loads(mock_publish.call_args_list[0][0][0])
        assert payload["event"] == "start_gun"
        # No tick timing -- just metadata
        assert "tick" not in payload
        assert payload.get("race_distance_mi") == 26.2188


# ---------------------------------------------------------------------------
# TestSimulationReadyGuard
# ---------------------------------------------------------------------------
class TestSimulationReadyGuard:
    """Guards that reject spawn_runners/start_race_collector without prepare_simulation."""

    @pytest.mark.asyncio
    async def test_spawn_runners_rejects_without_prepare(self):
        """spawn_runners should fail if prepare_simulation hasn't run."""
        ctx = _make_tool_context()
        # Don't set simulation_ready
        result = await spawn_runners(count=10, tool_context=ctx)
        assert result["status"] == "error"
        assert "prepare_simulation" in result["message"]

    @pytest.mark.asyncio
    async def test_start_race_collector_rejects_without_prepare(self):
        """start_race_collector should fail if prepare_simulation hasn't run."""
        ctx = _make_tool_context()
        result = await start_race_collector(tool_context=ctx)
        assert result["status"] == "error"
        assert "prepare_simulation" in result["message"]


# ---------------------------------------------------------------------------
# TestTrafficModelBuilding
# ---------------------------------------------------------------------------
class TestTrafficModelBuilding:
    """Tests for traffic model initialization in prepare_simulation."""

    @pytest.mark.asyncio
    async def test_builds_traffic_model_with_linestring_route(self):
        """prepare_simulation should build traffic_model when route has LineString features."""
        plan = {
            "action": "execute",
            "narrative": "Traffic test",
            "route": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-115.0, 36.0], [-115.01, 36.01], [-115.02, 36.02]],
                        },
                        "properties": {"name": "Las Vegas Blvd"},
                    },
                ],
            },
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"
        assert "traffic_model" in ctx.state
        traffic_model = ctx.state["traffic_model"]
        assert "segment_index" in traffic_model
        assert "ticks_closed" in traffic_model
        assert len(traffic_model["segment_index"]) > 0
        assert traffic_model["ticks_closed"] == {}

    @pytest.mark.asyncio
    async def test_no_traffic_model_without_route_features(self):
        """prepare_simulation should NOT build traffic_model when route has no features."""
        plan = {
            "action": "execute",
            "narrative": "No route test",
            "route": {"type": "FeatureCollection", "features": []},
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"
        assert "traffic_model" not in ctx.state

    @pytest.mark.asyncio
    async def test_no_traffic_model_without_route(self):
        """prepare_simulation should NOT build traffic_model when route is empty."""
        plan = {
            "action": "execute",
            "narrative": "No route",
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"
        assert "traffic_model" not in ctx.state


# ---------------------------------------------------------------------------
# Spawn readiness gate tests
# ---------------------------------------------------------------------------
class TestSpawnReadinessGate:
    """Tests for the spawn readiness gate in fire_start_gun."""

    @pytest.mark.asyncio
    async def test_fire_start_gun_waits_for_all_runners_registered(self):
        """fire_start_gun should poll simulation_registry until all runners are registered."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1", "r-2", "r-3"],
                "simulation_id": "sim-99",
            }
        )

        # Simulate registry returning partial results, then full
        call_count = 0

        async def mock_mget(*keys):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First poll: only 1 of 3 registered
                return [b"sim-99", None, None]
            # Second poll: all registered
            return [b"sim-99", b"sim-99", b"sim-99"]

        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(side_effect=mock_mget)

        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch("agents.simulator.broadcast.get_shared_redis_client", return_value=mock_redis),
            patch("agents.simulator.broadcast.asyncio.sleep", AsyncMock()),
        ):
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"
        assert call_count >= 2, "Should have polled at least twice"

    @pytest.mark.asyncio
    async def test_fire_start_gun_proceeds_without_redis(self):
        """fire_start_gun should proceed immediately if Redis is unavailable."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1", "r-2"],
                "simulation_id": "sim-100",
            }
        )

        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch("agents.simulator.broadcast.get_shared_redis_client", return_value=None),
        ):
            result = await fire_start_gun(tool_context=ctx)

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_fire_start_gun_proceeds_on_timeout(self):
        """fire_start_gun should proceed after timeout even if not all runners registered."""
        ctx = _make_tool_context(
            state={
                "runner_session_ids": ["r-1", "r-2", "r-3"],
                "simulation_id": "sim-101",
            }
        )

        # Always return partial results (simulates slow spawn)
        async def mock_mget(*keys):
            return [b"sim-101", None, None]

        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(side_effect=mock_mget)

        with (
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch("agents.simulator.broadcast.get_shared_redis_client", return_value=mock_redis),
            patch("agents.simulator.broadcast.asyncio.sleep", AsyncMock()),
            patch("agents.simulator.broadcast.time.monotonic", side_effect=[0, 0.5, 1.0, 61.0]),
        ):
            result = await fire_start_gun(tool_context=ctx)

        # Should still succeed (proceeds with partial runners after timeout)
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Boundary validator: prepare_simulation rejects shape-corrupt route_geojson
# ---------------------------------------------------------------------------


class TestPrepareSimulationShapeValidation:
    """prepare_simulation MUST reject corrupt route_geojson shapes BEFORE
    handing them to build_segment_distance_index, which would otherwise
    raise ``AttributeError: 'str' object has no attribute 'get'``."""

    @pytest.mark.asyncio
    async def test_rejects_stringified_features_in_plan_payload(self):
        """The exact production failure shape: features are JSON strings."""
        good_feature = {
            "type": "Feature",
            "properties": {"name": "Strip"},
            "geometry": {"type": "LineString", "coordinates": [[-115.17, 36.08]]},
        }
        plan = {
            "action": "execute",
            "narrative": "x",
            "route": {
                "type": "FeatureCollection",
                "features": [json.dumps(good_feature)],  # corrupt: each feature stringified
            },
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "error"
        assert "feature" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_features_not_a_list(self):
        plan = {
            "action": "execute",
            "narrative": "x",
            "route": {"type": "FeatureCollection", "features": "oops"},
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "error"
        assert "list" in result["message"].lower() or "feature" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_accepts_well_formed_route(self):
        """Well-formed routes still proceed through the validator."""
        plan = {
            "action": "execute",
            "narrative": "x",
            "route": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Strip"},
                        "geometry": {"type": "LineString", "coordinates": [[-115.17, 36.08]]},
                    }
                ],
            },
        }
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_accepts_empty_route_no_traffic_model(self):
        """Plan without route data is allowed (no traffic model built)."""
        plan = {"action": "execute", "narrative": "x", "route": {}}
        ctx = _make_tool_context()

        result = await prepare_simulation(plan_json=json.dumps(plan), tool_context=ctx)

        assert result["status"] == "success"
