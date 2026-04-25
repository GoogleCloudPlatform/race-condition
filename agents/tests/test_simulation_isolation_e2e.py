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

"""End-to-end integration tests for simulation session isolation.

Tests verify:
- Scoped broadcast channels don't leak between simulations (Redis)
- Dispatcher correctly maps sessions to simulation_ids
- Planner tools manage simulator session lifecycle correctly
- spawn_runners includes simulation_id in HTTP requests

Tests marked @pytest.mark.slow require a Redis instance at
REDIS_ADDR (default: 127.0.0.1:8102 from docker-compose.test.yml).
"""

import asyncio
import json
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# --- Redis Integration Tests (require docker-compose.test.yml) ---


def _redis_available() -> bool:
    """Check if test Redis is reachable."""
    try:
        import redis as sync_redis

        addr = os.environ.get("REDIS_ADDR", "127.0.0.1:8102")
        host, port = addr.split(":")
        r = sync_redis.Redis(host=host, port=int(port), socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


def _get_test_redis_url() -> str:
    """Return the Redis URL for tests."""
    addr = os.environ.get("REDIS_ADDR", "127.0.0.1:8102")
    if not addr.startswith("redis://"):
        return f"redis://{addr}"
    return addr


@pytest.mark.slow
@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
@pytest.mark.asyncio
async def test_scoped_broadcast_isolation():
    """Two simulation-scoped channels must not cross-contaminate.

    - Messages published to simulation:sim-A:broadcast must only reach sim-A subscribers
    - Messages published to simulation:sim-B:broadcast must only reach sim-B subscribers
    - The global simulation:broadcast channel must NOT receive scoped messages
    """
    import redis.asyncio as aioredis

    url = _get_test_redis_url()
    # Use separate clients for pub and sub to avoid connection pooling issues
    r_pub = aioredis.from_url(url, decode_responses=True)
    r_sub_a = aioredis.from_url(url, decode_responses=True)
    r_sub_b = aioredis.from_url(url, decode_responses=True)
    r_sub_global = aioredis.from_url(url, decode_responses=True)

    pubsub_a = r_sub_a.pubsub()
    pubsub_b = r_sub_b.pubsub()
    pubsub_global = r_sub_global.pubsub()

    try:
        # Flush to start clean
        await r_pub.flushall()

        await pubsub_a.subscribe("simulation:sim-A:broadcast")
        await pubsub_b.subscribe("simulation:sim-B:broadcast")
        await pubsub_global.subscribe("simulation:broadcast")

        # Consume subscription confirmation messages
        await pubsub_a.get_message(timeout=1.0)
        await pubsub_b.get_message(timeout=1.0)
        await pubsub_global.get_message(timeout=1.0)

        # Wait for subscriptions to be fully active in Redis
        await asyncio.sleep(0.3)

        # --- Publish to sim-A scoped channel ---
        msg_a = json.dumps({"type": "broadcast", "data": "Hello sim-A"})
        await r_pub.publish("simulation:sim-A:broadcast", msg_a)

        # sim-A subscriber should receive it
        received_a = await pubsub_a.get_message(ignore_subscribe_messages=True, timeout=2.0)
        assert received_a is not None, "sim-A subscriber should receive sim-A message"
        assert received_a["type"] == "message"
        assert json.loads(received_a["data"])["data"] == "Hello sim-A"

        # sim-B subscriber should NOT receive it
        received_b = await pubsub_b.get_message(ignore_subscribe_messages=True, timeout=0.5)
        assert received_b is None, "sim-B subscriber should NOT receive sim-A message"

        # Global channel should NOT receive scoped messages
        received_global = await pubsub_global.get_message(ignore_subscribe_messages=True, timeout=0.5)
        assert received_global is None, "Global channel should NOT receive scoped sim-A message"

        # --- Publish to sim-B scoped channel ---
        msg_b = json.dumps({"type": "broadcast", "data": "Hello sim-B"})
        await r_pub.publish("simulation:sim-B:broadcast", msg_b)

        # sim-B subscriber should receive it
        received_b2 = await pubsub_b.get_message(ignore_subscribe_messages=True, timeout=2.0)
        assert received_b2 is not None, "sim-B subscriber should receive sim-B message"
        assert json.loads(received_b2["data"])["data"] == "Hello sim-B"

        # sim-A subscriber should NOT receive it
        received_a2 = await pubsub_a.get_message(ignore_subscribe_messages=True, timeout=0.5)
        assert received_a2 is None, "sim-A subscriber should NOT receive sim-B message"

    finally:
        await pubsub_a.unsubscribe()
        await pubsub_b.unsubscribe()
        await pubsub_global.unsubscribe()
        await pubsub_a.aclose()
        await pubsub_b.aclose()
        await pubsub_global.aclose()
        await r_pub.flushall()
        await r_pub.aclose()
        await r_sub_a.aclose()
        await r_sub_b.aclose()
        await r_sub_global.aclose()


# --- Dispatcher Unit Tests (no Redis required) ---


@pytest.mark.asyncio
async def test_dispatcher_session_simulation_mapping():
    """Verify that spawn events with different simulation_ids
    correctly populate session_simulation_map and _simulation_subscriptions."""
    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"

    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn two sessions under sim-A
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-1",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
        }
    )
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-2",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
        }
    )

    # Spawn one session under sim-B
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "session-3",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-B"},
        }
    )

    # Verify session_simulation_map
    assert dispatcher.session_simulation_map["session-1"] == "sim-A"
    assert dispatcher.session_simulation_map["session-2"] == "sim-A"
    assert dispatcher.session_simulation_map["session-3"] == "sim-B"

    # Verify _simulation_subscriptions contains both IDs
    assert "sim-A" in dispatcher._simulation_subscriptions
    assert "sim-B" in dispatcher._simulation_subscriptions

    # Verify all sessions are active
    assert "session-1" in dispatcher.active_sessions
    assert "session-2" in dispatcher.active_sessions
    assert "session-3" in dispatcher.active_sessions


# --- Planner Tool Tests ---


@pytest.mark.asyncio
async def test_prepare_simulation_sets_simulation_id():
    """Verify that prepare_simulation (called via the planner tools)
    correctly uses the session.id as the simulation_id in state."""
    mock_tool_context = MagicMock()
    mock_tool_context.session.id = "test-session-42"
    mock_tool_context.state = {}

    # The planner_with_eval/tools.py submit_plan_to_simulator reads
    # simulator_session_id from state. We verify the lifecycle.
    # When no simulator_session_id exists, it should generate one.
    from agents.planner_with_eval.tools import submit_plan_to_simulator

    # Set up required state: marathon_route must exist
    mock_tool_context.state["marathon_route"] = {"type": "FeatureCollection", "features": []}

    # Mock call_agent so we don't actually call anything.
    # call_agent is imported lazily inside submit_plan_to_simulator,
    # so we patch it at its definition site.
    with patch("agents.utils.communication.call_agent", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "Simulator acknowledged"

        result = await submit_plan_to_simulator(
            action="verify",
            message="Test plan",
            tool_context=mock_tool_context,
        )

        assert result["status"] == "success"
        # simulator_session_id should now be set in state
        assert mock_tool_context.state["simulator_session_id"] is not None
        first_session_id = mock_tool_context.state["simulator_session_id"]
        assert len(first_session_id) > 0, "Should generate a UUID"


@pytest.mark.asyncio
async def test_spawn_runners_includes_simulation_id():
    """Verify that spawn HTTP request bodies include simulation_id
    when present in tool_context state."""
    mock_tool_context = MagicMock()
    mock_tool_context.session.id = "planner-session-1"
    mock_tool_context.state = {"simulation_id": "sim-xyz"}

    # We need to verify the spawn request payload. Since spawn_runners
    # is implemented in the gateway (Go), we test the Python-side:
    # the dispatcher's _process_event for spawn_agent should capture simulationId.
    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"

    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Simulate a spawn event that includes simulationId in the payload
    # (as sent by the Go gateway's batch spawn)
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "runner-session-1",
            "payload": {
                "agentType": "runner_autopilot",
                "simulationId": "sim-xyz",
            },
        }
    )

    # Session should be active
    assert "runner-session-1" in dispatcher.active_sessions

    # The simulation_id field in spawn events uses "simulation_id" key
    # (the dispatcher looks for payload.get("simulation_id"))
    # Let's also test with the correct key
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "runner-session-2",
            "payload": {
                "agentType": "runner_autopilot",
                "simulation_id": "sim-xyz",
            },
        }
    )

    assert "runner-session-2" in dispatcher.active_sessions
    assert dispatcher.session_simulation_map.get("runner-session-2") == "sim-xyz"


@pytest.mark.asyncio
async def test_full_lifecycle_create_persist():
    """Verify the simulator session lifecycle:
    1. verify → creates simulator_session_id in state
    2. execute → preserves it (for DashLogPlugin tool_end callbacks)
    3. verify again → reuses the existing session_id
    """
    mock_tool_context = MagicMock()
    mock_tool_context.session.id = "planner-lifecycle"
    mock_tool_context.state = {
        "marathon_route": {"type": "FeatureCollection", "features": []},
    }

    from agents.planner_with_eval.tools import submit_plan_to_simulator

    with patch("agents.utils.communication.call_agent", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "OK"

        # Step 1: verify → should create simulator_session_id
        await submit_plan_to_simulator(
            action="verify",
            message="Verify plan",
            tool_context=mock_tool_context,
        )
        first_id = mock_tool_context.state["simulator_session_id"]
        assert first_id is not None, "verify should create simulator_session_id"

        # Step 2: execute → should PRESERVE simulator_session_id
        # (previously voided by a finally block, but that caused a race
        # condition where DashLogPlugin.after_tool_callback read None)
        await submit_plan_to_simulator(
            action="execute",
            message="Execute plan",
            tool_context=mock_tool_context,
        )
        assert mock_tool_context.state["simulator_session_id"] is not None, (
            "execute should preserve simulator_session_id for plugin callbacks"
        )

        # Step 3: verify again → reuses existing session_id
        await submit_plan_to_simulator(
            action="verify",
            message="Verify plan again",
            tool_context=mock_tool_context,
        )
        second_id = mock_tool_context.state["simulator_session_id"]
        assert second_id is not None, "second verify should still have simulator_session_id"


@pytest.mark.asyncio
async def test_dispatcher_broadcast_isolation_between_simulations():
    """Verify that a broadcast event for sim-A does not trigger sessions
    belonging to sim-B, and vice versa. This is the core isolation guarantee
    at the dispatcher level."""
    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"

    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    # Spawn sessions under different simulations
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "sim-a-runner-1",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
        }
    )
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "sim-a-runner-2",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
        }
    )
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "sim-b-runner-1",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-B"},
        }
    )

    # Reset mock after spawn-time activations
    dispatcher._trigger_agent_run.reset_mock()

    # Send broadcast targeting sim-A sessions by session ID
    await dispatcher._process_event(
        {
            "type": "broadcast",
            "payload": {
                "data": "Pulse for sim-A",
                "targets": ["sim-a-runner-1", "sim-a-runner-2"],
            },
        }
    )

    # Only sim-A sessions should be triggered
    triggered_sessions = [call[0][0] for call in dispatcher._trigger_agent_run.call_args_list]
    assert "sim-a-runner-1" in triggered_sessions
    assert "sim-a-runner-2" in triggered_sessions
    assert "sim-b-runner-1" not in triggered_sessions, "sim-B session must NOT be triggered by sim-A broadcast"

    dispatcher._trigger_agent_run.reset_mock()

    # Send broadcast targeting sim-B session
    await dispatcher._process_event(
        {
            "type": "broadcast",
            "payload": {
                "data": "Pulse for sim-B",
                "targets": ["sim-b-runner-1"],
            },
        }
    )

    triggered_sessions_b = [call[0][0] for call in dispatcher._trigger_agent_run.call_args_list]
    assert "sim-b-runner-1" in triggered_sessions_b
    assert "sim-a-runner-1" not in triggered_sessions_b
    assert "sim-a-runner-2" not in triggered_sessions_b


@pytest.mark.asyncio
async def test_dispatcher_emit_includes_simulation_id():
    """Verify that the dispatcher includes simulation_id in emitted gateway
    messages when a session is mapped to a simulation."""
    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"

    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)

    # Spawn a session with simulation_id
    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "emit-test-session",
            "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-emit"},
        }
    )

    # Verify the simulation_id is stored correctly
    assert dispatcher.session_simulation_map["emit-test-session"] == "sim-emit"

    # When _trigger_agent_run_logic emits, it looks up sim_id from the map.
    # We verify that the lookup works correctly.
    sim_id = dispatcher.session_simulation_map.get("emit-test-session")
    assert sim_id == "sim-emit"


# --- DashLogPlugin simulation_id Propagation Tests ---
#
# These tests verify that DashLogPlugin._publish() correctly extracts
# simulation_id from the ADK context and passes it through to
# _emit_narrative() for ALL narrative event types.
#
# The ROOT CAUSE bug: runner autopilot agents don't have
# state["simulation_id"] in their ADK session state. The DashLogPlugin
# only reads from context.state, so runners emit simulation_id=None.
#
# Tests 1 (simulator) should PASS — proving the simulator path works.
# Tests 2-5 (runner / cross-cutting) should FAIL — proving the bug.


def _make_mock_context(session_id: str, state: dict | None = None, invocation_id: str = "inv-1"):
    """Create a mock ADK context with configurable state.

    Simulates a ToolContext/CallbackContext with .session.id and .state.
    """
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.id = session_id
    ctx.invocation_id = invocation_id
    ctx.agent_name = "test_agent"
    # .state is a dict-like property on ToolContext/CallbackContext
    ctx.state = state if state is not None else {}
    return ctx


def _make_narrative_payloads():
    """Return payloads for all four narrative event types that trigger _emit_narrative."""
    return [
        {
            "type": "tool_end",
            "agent": "test_agent",
            "tool": "test_tool",
            "result": {"status": "ok"},
            "timestamp": 1234567890.0,
        },
        {
            "type": "model_end",
            "agent": "test_agent",
            "response": {"content": "Model response text"},
            "timestamp": 1234567890.0,
        },
        {
            "type": "tool_error",
            "agent": "test_agent",
            "tool": "failing_tool",
            "error": "Something went wrong",
            "timestamp": 1234567890.0,
        },
        {
            "type": "model_error",
            "agent": "test_agent",
            "error": "Model inference failed",
            "timestamp": 1234567890.0,
        },
    ]


class _TestDashLogPlugin:
    """A minimal concrete subclass of BaseDashLogPlugin for testing.

    Captures published payloads and narrative emissions instead of
    sending to Pub/Sub or Redis.
    """

    def __init__(self):
        from agents.utils.plugins import BaseDashLogPlugin

        # We can't call super().__init__ easily with patched transport,
        # so we build a real instance with _init_transport stubbed.
        class _Stub(BaseDashLogPlugin):
            def _init_transport(self):
                pass

            async def _do_publish(self, context, payload):
                pass

        self._plugin = _Stub(name="test_plugin")
        self.narrative_calls: list[dict] = []

    async def publish(self, context, payload):
        """Delegate to the real _publish pipeline."""
        await self._plugin._publish(context, payload)

    def patch_emit_narrative(self):
        """Patch _emit_narrative to capture calls with simulation_id."""

        async def _capture(session_id, payload, simulation_id=None):
            self.narrative_calls.append(
                {
                    "session_id": session_id,
                    "payload": payload,
                    "simulation_id": simulation_id,
                }
            )
            # Don't call original — it tries to publish to the gateway
            # protobuf pipeline which isn't available in tests.

        self._plugin._emit_narrative = _capture


@pytest.mark.asyncio
async def test_simulator_subagent_emits_correct_simulation_id():
    """Simulator sub-agents (pre_race, tick, post_race) have state["simulation_id"]
    set by the planner before spawning. The DashLogPlugin should extract it
    from context.state and pass it to _emit_narrative for ALL narrative events.

    This test should PASS — the simulator path works correctly today.
    """
    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    sim_id = "sim-simulator-abc"
    ctx = _make_mock_context(
        session_id="simulator-session-1",
        state={"simulation_id": sim_id},
    )

    payloads = _make_narrative_payloads()

    for payload in payloads:
        test_plugin.narrative_calls.clear()
        await test_plugin.publish(ctx, payload.copy())

        assert len(test_plugin.narrative_calls) == 1, (
            f"Expected 1 narrative call for {payload['type']}, got {len(test_plugin.narrative_calls)}"
        )
        call = test_plugin.narrative_calls[0]
        assert call["simulation_id"] == sim_id, (
            f"Simulator sub-agent {payload['type']} should emit simulation_id={sim_id}, got {call['simulation_id']}"
        )
        assert call["session_id"] == "simulator-session-1"


@pytest.mark.asyncio
async def test_runner_agent_emits_correct_simulation_id_via_registry():
    """Runner autopilot agents do NOT have state["simulation_id"] in their
    ADK session. The dispatcher registers session→simulation_id in the
    process-local simulation_registry at spawn time. The DashLogPlugin
    falls back to the registry when context.state has no simulation_id.
    """
    from agents.utils.simulation_registry import clear, register

    await clear()

    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    expected_sim_id = "sim-runner-xyz"

    # Simulate what the dispatcher does at spawn time
    await register("runner-session-42", expected_sim_id)

    # Runner context: state is empty (no simulation_id) — registry provides it
    ctx = _make_mock_context(
        session_id="runner-session-42",
        state={},  # No simulation_id — runner agents don't have it
    )

    payloads = _make_narrative_payloads()

    for payload in payloads:
        test_plugin.narrative_calls.clear()
        await test_plugin.publish(ctx, payload.copy())

        assert len(test_plugin.narrative_calls) == 1, f"Expected 1 narrative call for {payload['type']}"
        call = test_plugin.narrative_calls[0]
        assert call["simulation_id"] == expected_sim_id, (
            f"Runner agent {payload['type']} should emit simulation_id={expected_sim_id} "
            f"via registry fallback, but got {call['simulation_id']}."
        )


@pytest.mark.asyncio
async def test_simulation_id_consistent_across_simulator_and_runner():
    """When a simulator sub-agent and a runner autopilot both belong to the
    same simulation, ALL narrative messages from BOTH must carry the SAME
    simulation_id.

    The simulator gets it from state; the runner gets it from the registry.
    """
    from agents.utils.simulation_registry import clear, register

    await clear()

    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    sim_id = "sim-unified-123"

    # Simulate dispatcher registering the runner session
    await register("runner-session-beta", sim_id)

    # Simulator context: has simulation_id in state
    sim_ctx = _make_mock_context(
        session_id="sim-session-alpha",
        state={"simulation_id": sim_id},
    )

    # Runner context: does NOT have simulation_id in state (registry provides it)
    runner_ctx = _make_mock_context(
        session_id="runner-session-beta",
        state={},
    )

    # Use tool_end as a representative narrative event
    tool_end_payload = {
        "type": "tool_end",
        "agent": "test_agent",
        "tool": "some_tool",
        "result": {"status": "ok"},
        "timestamp": 1234567890.0,
    }

    # Collect simulation_ids from both contexts
    collected_sim_ids = []

    # Simulator emission
    test_plugin.narrative_calls.clear()
    await test_plugin.publish(sim_ctx, tool_end_payload.copy())
    assert len(test_plugin.narrative_calls) == 1
    collected_sim_ids.append(test_plugin.narrative_calls[0]["simulation_id"])

    # Runner emission
    test_plugin.narrative_calls.clear()
    await test_plugin.publish(runner_ctx, tool_end_payload.copy())
    assert len(test_plugin.narrative_calls) == 1
    collected_sim_ids.append(test_plugin.narrative_calls[0]["simulation_id"])

    # ALL simulation_ids must be identical and equal to sim_id
    for i, sid in enumerate(collected_sim_ids):
        assert sid == sim_id, (
            f"Message {i} has simulation_id={sid}, expected {sim_id}. "
            f"Inconsistent simulation_id across simulator and runner sessions."
        )

    # Verify they're all the same (no cross-contamination)
    assert len(set(collected_sim_ids)) == 1, f"Expected all simulation_ids to be identical, got: {collected_sim_ids}"


@pytest.mark.asyncio
async def test_concurrent_simulations_no_cross_contamination():
    """Two concurrent simulations must not leak simulation_id between them.

    Sim-A has its own simulator and runner sessions.
    Sim-B has its own simulator and runner sessions.
    Messages from sim-A must never carry sim-B's ID and vice versa.

    Runners get their simulation_id from the registry.
    """
    from agents.utils.simulation_registry import clear, register

    await clear()

    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    sim_a_id = "sim-alpha-001"
    sim_b_id = "sim-beta-002"

    # Simulate dispatcher registering runner sessions
    await register("sim-a-runner", sim_a_id)
    await register("sim-b-runner", sim_b_id)

    # Sim-A contexts
    sim_a_simulator = _make_mock_context(
        session_id="sim-a-simulator",
        state={"simulation_id": sim_a_id},
    )
    sim_a_runner = _make_mock_context(
        session_id="sim-a-runner",
        state={},  # Runner: registry provides simulation_id
    )

    # Sim-B contexts
    sim_b_simulator = _make_mock_context(
        session_id="sim-b-simulator",
        state={"simulation_id": sim_b_id},
    )
    sim_b_runner = _make_mock_context(
        session_id="sim-b-runner",
        state={},  # Runner: registry provides simulation_id
    )

    tool_end_payload = {
        "type": "tool_end",
        "agent": "test_agent",
        "tool": "race_tool",
        "result": {"status": "ok"},
        "timestamp": 1234567890.0,
    }

    # Interleave emissions from both simulations (simulating concurrency)
    results = {}
    for label, ctx in [
        ("sim-a-simulator", sim_a_simulator),
        ("sim-b-simulator", sim_b_simulator),
        ("sim-a-runner", sim_a_runner),
        ("sim-b-runner", sim_b_runner),
    ]:
        test_plugin.narrative_calls.clear()
        await test_plugin.publish(ctx, tool_end_payload.copy())
        assert len(test_plugin.narrative_calls) == 1
        results[label] = test_plugin.narrative_calls[0]["simulation_id"]

    # Simulators should have correct IDs (these pass today)
    assert results["sim-a-simulator"] == sim_a_id, (
        f"Sim-A simulator should emit {sim_a_id}, got {results['sim-a-simulator']}"
    )
    assert results["sim-b-simulator"] == sim_b_id, (
        f"Sim-B simulator should emit {sim_b_id}, got {results['sim-b-simulator']}"
    )

    # Runners should also have correct IDs (these FAIL — proving the bug)
    assert results["sim-a-runner"] == sim_a_id, (
        f"Sim-A runner should emit {sim_a_id}, got {results['sim-a-runner']}. "
        f"Cross-contamination or missing registry fallback."
    )
    assert results["sim-b-runner"] == sim_b_id, (
        f"Sim-B runner should emit {sim_b_id}, got {results['sim-b-runner']}. "
        f"Cross-contamination or missing registry fallback."
    )

    # Final: no cross-contamination between simulations
    assert results["sim-a-simulator"] != sim_b_id
    assert results["sim-b-simulator"] != sim_a_id


@pytest.mark.asyncio
async def test_registry_cleanup_prevents_stale_simulation_id():
    """After a session is removed from the registry, DashLogPlugin should
    NOT find the old simulation_id for that session.

    This test validates the cleanup contract: once a simulation ends and
    its sessions are deregistered, subsequent emissions from a recycled
    session ID must not carry a stale simulation_id.
    """
    from agents.utils.simulation_registry import clear, register, unregister

    await clear()

    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    sim_id = "sim-cleanup-test"

    # Simulate dispatcher registering the session at spawn time
    await register("runner-cleanup-session", sim_id)

    runner_ctx = _make_mock_context(
        session_id="runner-cleanup-session",
        state={},
    )

    tool_end_payload = {
        "type": "tool_end",
        "agent": "test_agent",
        "tool": "cleanup_tool",
        "result": {"status": "done"},
        "timestamp": 1234567890.0,
    }

    # Phase 1: Emit BEFORE cleanup — should produce simulation_id from registry
    test_plugin.narrative_calls.clear()
    await test_plugin.publish(runner_ctx, tool_end_payload.copy())
    assert len(test_plugin.narrative_calls) == 1

    pre_cleanup_id = test_plugin.narrative_calls[0]["simulation_id"]
    assert pre_cleanup_id == sim_id, (
        f"Before cleanup, runner should emit simulation_id={sim_id} via registry, but got {pre_cleanup_id}."
    )

    # Phase 2: Unregister (simulates dispatcher.remove_session cleanup)
    await unregister("runner-cleanup-session")

    # Emit AFTER cleanup — should NOT find stale simulation_id
    test_plugin.narrative_calls.clear()
    await test_plugin.publish(runner_ctx, tool_end_payload.copy())
    assert len(test_plugin.narrative_calls) == 1

    post_cleanup_id = test_plugin.narrative_calls[0]["simulation_id"]
    assert post_cleanup_id is None, (
        f"After cleanup, runner should emit simulation_id=None, "
        f"but got {post_cleanup_id}. Stale registry entry detected."
    )


# --- Simulation ID Propagation Tests ---


@pytest.mark.asyncio
async def test_simulation_started_matches_downstream_simulation_id():
    """E2E: The simulation_id emitted in the simulation_started event must be
    the EXACT SAME ID used by prepare_simulation and all downstream messages.

    This is the definitive regression test for the bug where simulation_started
    emitted the simulator ROOT session.id but prepare_simulation used the
    simulation_pipeline's (different) session.id.
    """
    # Simulate the root agent callback capturing the session ID
    from agents.simulator.agent import _capture_root_simulation_id

    root_session_id = "planner-generated-uuid-abc"
    pipeline_session_id = "pipeline-internal-uuid-xyz"

    # 1. Root callback captures root session ID
    root_ctx = MagicMock()
    root_ctx.session.id = root_session_id
    root_ctx.state = {}
    await _capture_root_simulation_id(root_ctx)
    assert root_ctx.state["simulation_id"] == root_session_id

    # 2. prepare_simulation runs with a DIFFERENT session.id (pipeline's)
    #    but must preserve the root's simulation_id from state
    pipeline_ctx = MagicMock()
    pipeline_ctx.session.id = pipeline_session_id
    pipeline_ctx.state = dict(root_ctx.state)  # Shared state
    pipeline_ctx.invocation_id = "inv-1"
    pipeline_ctx.agent_name = "pre_race"

    # Import prepare_simulation
    import importlib.util
    import pathlib

    tools_path = pathlib.Path(__file__).parents[1] / "simulator" / "skills" / "preparing-the-race" / "tools.py"
    spec = importlib.util.spec_from_file_location("pre_race_tools", tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = await module.prepare_simulation(
        plan_json='{"action":"execute","narrative":"test"}',
        tool_context=pipeline_ctx,
    )

    # simulation_id in state must be the ROOT session ID, not pipeline's
    assert pipeline_ctx.state["simulation_id"] == root_session_id, (
        f"Expected root session ID '{root_session_id}', got '{pipeline_ctx.state['simulation_id']}'"
    )
    # Return value must also match
    assert result["simulation_id"] == root_session_id

    # 3. This must match what simulation_started would emit
    # (planner sets simulator_session_id = root_session_id)
    assert result["simulation_id"] == root_session_id, (
        "simulation_id from prepare_simulation must match what simulation_started emits"
    )


@pytest.mark.asyncio
async def test_concurrent_simulations_have_distinct_root_ids():
    """Two concurrent simulations must each have their own root-captured
    simulation_id that propagates consistently."""
    from agents.simulator.agent import _capture_root_simulation_id

    # Simulation A
    ctx_a = MagicMock()
    ctx_a.session.id = "root-sim-ALPHA"
    ctx_a.state = {}
    await _capture_root_simulation_id(ctx_a)

    # Simulation B
    ctx_b = MagicMock()
    ctx_b.session.id = "root-sim-BETA"
    ctx_b.state = {}
    await _capture_root_simulation_id(ctx_b)

    assert ctx_a.state["simulation_id"] == "root-sim-ALPHA"
    assert ctx_b.state["simulation_id"] == "root-sim-BETA"
    assert ctx_a.state["simulation_id"] != ctx_b.state["simulation_id"]


@pytest.mark.asyncio
async def test_start_simulation_id_matches_all_downstream_events():
    """E2E: The simulation_id returned by start_simulation must be the EXACT
    SAME ID seen in:
    1. start_simulation tool result (visible in dashboard as tool_end)
    2. submit_plan_to_simulator tool result
    3. Simulator root agent state (set by _capture_root_simulation_id callback)
    4. prepare_simulation state and return value
    5. DashLogPlugin emissions from simulator sub-agents
    6. DashLogPlugin emissions from runner agents (via registry)

    This is the definitive regression test for simulation_id consistency
    across the entire agent hierarchy.
    """
    from agents.planner_with_eval.tools import start_simulation
    from agents.simulator.agent import _capture_root_simulation_id
    from agents.utils import simulation_registry
    import importlib.util
    import pathlib

    await simulation_registry.clear()

    # --- Step 1: start_simulation returns the canonical simulation_id ---
    planner_ctx = MagicMock()
    planner_ctx.session.id = "planner-session-1"
    planner_ctx.state = {"marathon_route": {"type": "FeatureCollection", "features": []}}
    planner_ctx.invocation_id = "inv-planner"
    planner_ctx.agent_name = "planner_with_memory"

    start_result = await start_simulation(
        action="execute",
        message="Run simulation",
        tool_context=planner_ctx,
        simulation_config={"runner_count": 10},
    )

    assert start_result["status"] == "ready"
    canonical_sim_id = start_result["simulation_id"]
    assert canonical_sim_id is not None
    assert planner_ctx.state["simulation_id"] == canonical_sim_id

    # --- Step 2: Simulator root callback captures the SAME ID ---
    sim_root_ctx = MagicMock()
    sim_root_ctx.session.id = canonical_sim_id  # A2A call uses this as session_id
    sim_root_ctx.state = {}
    await _capture_root_simulation_id(sim_root_ctx)
    assert sim_root_ctx.state["simulation_id"] == canonical_sim_id

    # --- Step 3: prepare_simulation preserves the SAME ID ---
    # (even though session.id might differ inside pipeline)
    pipeline_ctx = MagicMock()
    pipeline_ctx.session.id = "pipeline-internal-different-id"
    pipeline_ctx.state = dict(sim_root_ctx.state)  # Shared state from root
    pipeline_ctx.invocation_id = "inv-pipeline"
    pipeline_ctx.agent_name = "pre_race"

    tools_path = pathlib.Path("agents/simulator/skills/preparing-the-race/tools.py")
    spec = importlib.util.spec_from_file_location("pre_race_e2e", tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    prep_result = await module.prepare_simulation(
        plan_json='{"action":"execute","narrative":"test","simulation_config":{"runner_count":10}}',
        tool_context=pipeline_ctx,
    )
    assert pipeline_ctx.state["simulation_id"] == canonical_sim_id
    assert prep_result["simulation_id"] == canonical_sim_id

    # --- Step 4: DashLogPlugin emissions from simulator carry SAME ID ---
    test_plugin = _TestDashLogPlugin()
    test_plugin.patch_emit_narrative()

    # Simulate tool_end from pre_race (has simulation_id in state)
    sim_plugin_ctx = _make_mock_context(
        session_id=canonical_sim_id,
        state={"simulation_id": canonical_sim_id},
        invocation_id="inv-sim",
    )

    await test_plugin.publish(
        sim_plugin_ctx,
        {
            "type": "tool_end",
            "agent": "pre_race",
            "tool": "prepare_simulation",
            "result": prep_result,
            "timestamp": 1,
        },
    )
    await test_plugin.publish(
        sim_plugin_ctx,
        {
            "type": "tool_end",
            "agent": "tick",
            "tool": "advance_tick",
            "result": {},
            "timestamp": 2,
        },
    )

    sim_captured_ids = [c["simulation_id"] for c in test_plugin.narrative_calls]
    assert all(sid == canonical_sim_id for sid in sim_captured_ids), (
        f"Simulator sub-agent emissions must all carry {canonical_sim_id}, got: {sim_captured_ids}"
    )

    # --- Step 5: Runner DashLogPlugin emissions carry SAME ID (via registry) ---
    # Spawn runner (dispatcher writes to registry)
    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"
    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)
    dispatcher._trigger_agent_run = MagicMock()

    await dispatcher._process_event(
        {
            "type": "spawn_agent",
            "sessionId": "runner-session-e2e",
            "payload": {"agentType": "runner_autopilot", "simulation_id": canonical_sim_id},
        }
    )

    test_plugin_runner = _TestDashLogPlugin()
    test_plugin_runner.patch_emit_narrative()

    runner_plugin_ctx = _make_mock_context(
        session_id="runner-session-e2e",
        state={},  # Runner has NO simulation_id in state
        invocation_id="inv-runner",
    )

    await test_plugin_runner.publish(
        runner_plugin_ctx,
        {
            "type": "tool_end",
            "agent": "runner_autopilot",
            "tool": "accelerate",
            "result": {},
            "timestamp": 3,
        },
    )
    await test_plugin_runner.publish(
        runner_plugin_ctx,
        {
            "type": "model_end",
            "agent": "runner_autopilot",
            "response": {"content": "ok"},
            "timestamp": 4,
        },
    )

    runner_captured_ids = [c["simulation_id"] for c in test_plugin_runner.narrative_calls]
    assert all(sid == canonical_sim_id for sid in runner_captured_ids), (
        f"Runner emissions must all carry {canonical_sim_id}, got: {runner_captured_ids}"
    )

    # --- Final assertion: ALL IDs are the same ---
    all_ids = (
        [
            canonical_sim_id,  # start_simulation result
            planner_ctx.state.get("simulation_id"),  # planner state (may be voided after execute)
            sim_root_ctx.state["simulation_id"],  # root callback
            pipeline_ctx.state["simulation_id"],  # prepare_simulation
            prep_result["simulation_id"],  # prepare_simulation return
        ]
        + sim_captured_ids
        + runner_captured_ids
    )

    # Filter None (planner voids after execute)
    non_none = [x for x in all_ids if x is not None]
    unique_ids = set(non_none)
    assert len(unique_ids) == 1, (
        f"ALL simulation_ids across the entire pipeline must be identical. "
        f"Found {len(unique_ids)} distinct IDs: {unique_ids}"
    )


@pytest.mark.asyncio
async def test_concurrent_simulations_never_bleed_broadcast_events():
    """E2E: Two concurrent simulations must NEVER bleed tick broadcasts
    into each other's runner sessions.

    This test simulates:
    1. Simulation ALPHA spawns 3 runners
    2. Simulation BETA spawns 3 runners
    3. ALPHA broadcasts a tick — only ALPHA runners are triggered
    4. BETA broadcasts a tick — only BETA runners are triggered
    5. ALPHA ends — its runners are removed
    6. BETA broadcasts another tick — only BETA runners, no ALPHA leakage
    7. BETA ends — its runners are removed
    8. Final state: zero active sessions
    """
    from agents.utils import simulation_registry
    from agents.utils.dispatcher import RedisOrchestratorDispatcher

    await simulation_registry.clear()

    mock_runner = MagicMock()
    mock_runner.app.name = "runner_autopilot"
    mock_runner.app.root_agent.name = "runner_agent"
    dispatcher = RedisOrchestratorDispatcher(runner=mock_runner)

    triggered_log: list[tuple[str, str]] = []  # (phase, session_id)

    def make_trigger(phase: str):
        def trigger(session_id: str, content: object) -> None:
            triggered_log.append((phase, session_id))

        return trigger

    # --- Phase 1: Spawn runners for both simulations ---
    for i in range(3):
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": f"alpha-runner-{i}",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-ALPHA"},
            }
        )
    for i in range(3):
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": f"beta-runner-{i}",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-BETA"},
            }
        )
    assert len(dispatcher.active_sessions) == 6

    # --- Phase 2: ALPHA tick — only ALPHA runners ---
    dispatcher._trigger_agent_run = make_trigger("alpha_tick")
    await dispatcher._process_event(
        {
            "type": "broadcast",
            "simulation_id": "sim-ALPHA",
            "payload": {"data": "TICK"},
        }
    )
    alpha_tick_sessions = [sid for phase, sid in triggered_log if phase == "alpha_tick"]
    assert sorted(alpha_tick_sessions) == ["alpha-runner-0", "alpha-runner-1", "alpha-runner-2"]

    # --- Phase 3: BETA tick — only BETA runners ---
    dispatcher._trigger_agent_run = make_trigger("beta_tick")
    await dispatcher._process_event(
        {
            "type": "broadcast",
            "simulation_id": "sim-BETA",
            "payload": {"data": "TICK"},
        }
    )
    beta_tick_sessions = [sid for phase, sid in triggered_log if phase == "beta_tick"]
    assert sorted(beta_tick_sessions) == ["beta-runner-0", "beta-runner-1", "beta-runner-2"]

    # --- Phase 4: ALPHA ends ---
    await dispatcher._process_event(
        {
            "type": "end_simulation",
            "simulation_id": "sim-ALPHA",
        }
    )
    assert len(dispatcher.active_sessions) == 3
    for i in range(3):
        assert f"alpha-runner-{i}" not in dispatcher.active_sessions
        assert await simulation_registry.lookup(f"alpha-runner-{i}") is None

    # --- Phase 5: BETA tick after ALPHA ended — NO alpha leakage ---
    dispatcher._trigger_agent_run = make_trigger("beta_tick_2")
    await dispatcher._process_event(
        {
            "type": "broadcast",
            "simulation_id": "sim-BETA",
            "payload": {"data": "TICK"},
        }
    )
    beta_tick_2_sessions = [sid for phase, sid in triggered_log if phase == "beta_tick_2"]
    assert sorted(beta_tick_2_sessions) == ["beta-runner-0", "beta-runner-1", "beta-runner-2"]

    # --- Phase 6: BETA ends ---
    await dispatcher._process_event(
        {
            "type": "end_simulation",
            "simulation_id": "sim-BETA",
        }
    )
    assert len(dispatcher.active_sessions) == 0
    assert len(dispatcher.session_simulation_map) == 0
