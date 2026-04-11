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

"""Tests for SimulationExecutor simulation_id bridging.

Validates that callable-mode AE instances correctly bridge simulation_id
from orchestration event payloads to the simulation registry, so that
DashLogPlugin can resolve simulation_id for events emitted by callable
agents.

This is the Python-side counterpart to the Go-side fix in
switchboard.go dispatchCallable (which writes simreg:sessions for the
A2A context_id).  The executor must re-register under the Vertex AI
session_id so DashLogPlugin (which looks up by session.id) can find it.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def _callable_mode(monkeypatch):
    """Set DISPATCH_MODE=callable to simulate Agent Engine environment."""
    monkeypatch.setenv("DISPATCH_MODE", "callable")


@pytest.fixture()
def _patch_simulation_registry():
    """Provide isolated simulation_registry with no Redis."""
    from agents.utils.simulation_registry import _context_map, _local

    _local.clear()
    _context_map.clear()
    with patch("agents.utils.simulation_executor.simulation_registry") as mock_reg:
        # Wire through to the real dicts for register/lookup/context
        async def _register(sid, sim_id):
            _local[sid] = sim_id

        async def _lookup(sid):
            return _local.get(sid)

        async def _register_context(vertex_sid, ctx_id):
            _context_map[vertex_sid] = ctx_id

        async def _get_context_id(vertex_sid):
            return _context_map.get(vertex_sid)

        mock_reg.register = AsyncMock(side_effect=_register)
        mock_reg.lookup = AsyncMock(side_effect=_lookup)
        mock_reg.register_context = AsyncMock(side_effect=_register_context)
        mock_reg.get_context_id = AsyncMock(side_effect=_get_context_id)
        yield mock_reg
    _local.clear()
    _context_map.clear()


def _make_executor(agent_name="test_agent"):
    """Create a SimulationExecutor with mocked internals."""
    from agents.utils.simulation_executor import SimulationExecutor

    executor = SimulationExecutor(
        agent_getter=lambda: MagicMock(),
        agent_name=agent_name,
    )
    # Pre-set dispatch mode (normally from env)
    executor._dispatch_mode = "callable"

    # Mock the runner and session manager so _init_runner() is a no-op
    mock_runner = MagicMock()
    mock_runner.app_name = "test_app"
    mock_runner.app.plugins = []

    # Mock run_async to return a simple final event
    final_event = MagicMock()
    final_event.is_final_response.return_value = True
    final_event.author = "agent"
    final_event.content.parts = [MagicMock(text="test response")]

    async def _run_async(**kwargs):
        yield final_event

    mock_runner.run_async = _run_async

    executor._runner = mock_runner

    mock_session_mgr = AsyncMock()
    executor._session_manager = mock_session_mgr

    return executor, mock_session_mgr


def _make_request_context(query: str, context_id: str = "ctx-123"):
    """Create a minimal A2A RequestContext."""
    ctx = MagicMock()
    ctx.task_id = "task-1"
    ctx.context_id = context_id
    ctx.current_task = None

    msg = MagicMock()
    msg.metadata = {}
    ctx.message = msg
    ctx.get_user_input.return_value = query

    return ctx


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_spawn_registers_simulation_id(_patch_simulation_registry):
    """spawn_agent event should register context_id → simulation_id."""
    reg = _patch_simulation_registry
    executor, _ = _make_executor(agent_name="planner_with_eval")

    spawn_event = json.dumps(
        {
            "type": "spawn_agent",
            "sessionId": "sess-abc",
            "payload": {
                "agentType": "planner_with_eval",
                "simulation_id": "sim-xyz",
            },
        }
    )

    ctx = _make_request_context(spawn_event, context_id="sess-abc")
    event_queue = AsyncMock()

    await executor.execute(ctx, event_queue)

    # Should have registered context_id → simulation_id
    reg.register.assert_called_with("sess-abc", "sim-xyz")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_broadcast_bridges_simulation_id_to_vertex_session(
    _patch_simulation_registry,
):
    """broadcast event should bridge simulation_id from context_id to vertex session_id."""
    reg = _patch_simulation_registry

    executor, mock_session_mgr = _make_executor(agent_name="planner_with_eval")

    # Simulate: spawn already registered context_id → simulation_id
    from agents.utils.simulation_registry import _local

    _local["ctx-broadcast"] = "sim-broadcast-1"

    # SessionManager returns a DIFFERENT vertex session ID
    mock_session_mgr.get_or_create_session.return_value = "vertex-uuid-999"

    broadcast_event = json.dumps(
        {
            "type": "broadcast",
            "sessionId": "ctx-broadcast",
            "payload": {
                "targets": ["ctx-broadcast"],
                "data": json.dumps({"text": "tick advance"}),
            },
        }
    )

    ctx = _make_request_context(broadcast_event, context_id="ctx-broadcast")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        await executor.execute(ctx, event_queue)

    # Should have looked up simulation_id via context_id
    reg.lookup.assert_called_with("ctx-broadcast")
    # Should have re-registered under the vertex session ID
    reg.register.assert_called_with("vertex-uuid-999", "sim-broadcast-1")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_broadcast_with_simulation_id_in_payload(_patch_simulation_registry):
    """broadcast event with simulation_id in payload should use it directly."""
    reg = _patch_simulation_registry

    executor, mock_session_mgr = _make_executor(agent_name="simulator")
    mock_session_mgr.get_or_create_session.return_value = "vertex-uuid-888"

    broadcast_event = json.dumps(
        {
            "type": "broadcast",
            "sessionId": "ctx-sim",
            "payload": {
                "targets": ["ctx-sim"],
                "data": json.dumps({"text": "run simulation"}),
                "simulation_id": "sim-direct-payload",
            },
        }
    )

    ctx = _make_request_context(broadcast_event, context_id="ctx-sim")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        await executor.execute(ctx, event_queue)

    # Should have registered using the payload's simulation_id directly
    # (no need to fall back to registry lookup)
    reg.register.assert_called_with("vertex-uuid-888", "sim-direct-payload")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_telemetry_bridge_passes_simulation_id(_patch_simulation_registry):
    """Telemetry bridge emit_gateway_message should include simulation_id."""
    from agents.utils.simulation_registry import _local

    _local["ctx-telem"] = "sim-telem-1"

    executor, mock_session_mgr = _make_executor(agent_name="planner_with_eval")
    mock_session_mgr.get_or_create_session.return_value = "vertex-telem"

    broadcast_event = json.dumps(
        {
            "type": "broadcast",
            "payload": {
                "targets": ["ctx-telem"],
                "data": json.dumps({"text": "test telemetry"}),
            },
        }
    )

    ctx = _make_request_context(broadcast_event, context_id="ctx-telem")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        await executor.execute(ctx, event_queue)

        # The telemetry bridge should have passed simulation_id
        if mock_pulses.emit_gateway_message.called:
            call_kwargs = mock_pulses.emit_gateway_message.call_args
            assert call_kwargs.kwargs.get("simulation_id") == "sim-telem-1" or (
                len(call_kwargs.args) > 7 and call_kwargs.args[7] == "sim-telem-1"
            ), "emit_gateway_message must pass simulation_id from registry"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_no_simulation_id_still_works(_patch_simulation_registry):
    """Events without simulation_id should not crash and should NOT register a fake simulation_id."""
    reg = _patch_simulation_registry

    executor, mock_session_mgr = _make_executor(agent_name="simulator")
    mock_session_mgr.get_or_create_session.return_value = "vertex-no-sim"

    # Plain user message, not an orchestration event
    ctx = _make_request_context("Hello, simulator", context_id="ctx-plain")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        # Should not raise
        await executor.execute(ctx, event_queue)

    # Without a simulation_id from an orchestration event or registry
    # lookup, register should NOT be called.  Falling back to context_id
    # would pollute DashLogPlugin events and break Hub subscription
    # filters (see simulation_executor.py lines 416-419).
    reg.register.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_context_id_mapping_registered(_patch_simulation_registry):
    """SimulationExecutor should register vertex_session_id → context_id mapping."""
    reg = _patch_simulation_registry

    executor, mock_session_mgr = _make_executor(agent_name="planner_with_memory")
    # SessionManager returns a DIFFERENT vertex session ID
    mock_session_mgr.get_or_create_session.return_value = "vertex-99887766"

    # Plain user message (not an orchestration event)
    ctx = _make_request_context("Plan a marathon", context_id="spawn-uuid-abcd")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        await executor.execute(ctx, event_queue)

    # Should have registered the context mapping so DashLogPlugin can
    # map vertex session IDs back to spawn session UUIDs
    reg.register_context.assert_called_with("vertex-99887766", "spawn-uuid-abcd")


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_telemetry_bridge_uses_context_id(_patch_simulation_registry):
    """Telemetry bridge should use context_id (spawn UUID) in origin, not vertex session ID."""
    executor, mock_session_mgr = _make_executor(agent_name="planner_with_memory")
    mock_session_mgr.get_or_create_session.return_value = "vertex-numeric-id"

    ctx = _make_request_context("Plan a marathon", context_id="spawn-uuid-1234")
    event_queue = AsyncMock()

    with patch("agents.utils.simulation_executor.pulses") as mock_pulses:
        mock_pulses.emit_gateway_message = AsyncMock()
        await executor.execute(ctx, event_queue)

        if mock_pulses.emit_gateway_message.called:
            call_kwargs = mock_pulses.emit_gateway_message.call_args
            origin = call_kwargs.kwargs.get("origin") or call_kwargs.args[0]
            # Origin session_id should be the spawn UUID, not the vertex ID
            assert origin["session_id"] == "spawn-uuid-1234", (
                f"Telemetry bridge should use context_id 'spawn-uuid-1234' "
                f"in origin.session_id, got '{origin['session_id']}'"
            )


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_dedup_blocks_second_execution(_patch_simulation_registry):
    """Second execute() with same context_id should be dropped via Redis NX lock."""
    executor, mock_session_mgr = _make_executor(agent_name="simulator")
    mock_session_mgr.get_or_create_session.return_value = "vertex-session-1"

    ctx1 = _make_request_context('{"action":"execute","narrative":"test"}', context_id="sim-ctx-1")
    ctx2 = _make_request_context('{"action":"execute","narrative":"test"}', context_id="sim-ctx-1")

    mock_redis = MagicMock()
    # First call: NX succeeds (lock acquired)
    # Second call: NX fails (lock already held)
    mock_redis.set = AsyncMock(side_effect=[True, False])

    with patch("agents.utils.simulation_executor.get_shared_redis_client", return_value=mock_redis):
        eq1 = AsyncMock()
        await executor.execute(ctx1, eq1)

        eq2 = AsyncMock()
        await executor.execute(ctx2, eq2)

    # runner.run_async should only have been invoked for the first call
    actual = mock_session_mgr.get_or_create_session.call_count
    assert actual == 1, f"Expected 1 session creation (second should be deduped), got {actual}"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_dedup_allows_different_context_ids(_patch_simulation_registry):
    """Different context_ids should NOT be deduped."""
    executor, mock_session_mgr = _make_executor(agent_name="simulator")
    mock_session_mgr.get_or_create_session.return_value = "vertex-session-1"

    ctx1 = _make_request_context('{"action":"execute","narrative":"test"}', context_id="sim-ctx-1")
    ctx2 = _make_request_context('{"action":"execute","narrative":"test"}', context_id="sim-ctx-2")

    mock_redis = MagicMock()
    # Both NX calls succeed (different keys)
    mock_redis.set = AsyncMock(return_value=True)

    with patch("agents.utils.simulation_executor.get_shared_redis_client", return_value=mock_redis):
        eq1 = AsyncMock()
        await executor.execute(ctx1, eq1)

        eq2 = AsyncMock()
        await executor.execute(ctx2, eq2)

    assert mock_session_mgr.get_or_create_session.call_count == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("_callable_mode")
async def test_dedup_graceful_without_redis(_patch_simulation_registry):
    """When Redis is unavailable, dedup should be skipped (not crash)."""
    executor, mock_session_mgr = _make_executor(agent_name="simulator")
    mock_session_mgr.get_or_create_session.return_value = "vertex-session-1"

    ctx = _make_request_context('{"action":"execute","narrative":"test"}', context_id="sim-ctx-1")

    with patch("agents.utils.simulation_executor.get_shared_redis_client", return_value=None):
        eq = AsyncMock()
        await executor.execute(ctx, eq)

    # Should still proceed without Redis
    assert mock_session_mgr.get_or_create_session.call_count == 1
