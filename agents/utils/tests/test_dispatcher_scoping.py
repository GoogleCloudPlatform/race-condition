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

"""Tests for simulation-scoped dispatcher subscription (Task 11).

Extended with:
- C1: Relay channel scoping (relays to scoped channel when simulation_id present)
- I1: Dispatcher cleanup via remove_session()
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.utils.dispatcher import RedisOrchestratorDispatcher


class TestDispatcherSimulationScoping:
    """Tests for simulation_id-scoped subscription tracking."""

    def _make_dispatcher(self, agent_type: str = "runner_autopilot") -> RedisOrchestratorDispatcher:
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_spawn_with_simulation_id_stores_mapping(self):
        """Spawning with simulation_id should store session->simulation mapping."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-1",
                "payload": {
                    "agentType": "runner_autopilot",
                    "simulation_id": "sim-abc-123",
                },
            }
        )

        assert "session-1" in dispatcher.active_sessions
        assert dispatcher.session_simulation_map["session-1"] == "sim-abc-123"
        assert "sim-abc-123" in dispatcher._simulation_subscriptions

    @pytest.mark.asyncio
    async def test_spawn_without_simulation_id_works(self):
        """Spawning without simulation_id should still work (backward compat)."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-legacy",
                "payload": {"agentType": "runner_autopilot"},
            }
        )

        assert "session-legacy" in dispatcher.active_sessions
        assert "session-legacy" not in dispatcher.session_simulation_map

    @pytest.mark.asyncio
    async def test_multiple_sessions_same_simulation(self):
        """Multiple sessions for the same simulation_id should all be tracked."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        for i in range(3):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"session-{i}",
                    "payload": {
                        "agentType": "runner_autopilot",
                        "simulation_id": "sim-shared",
                    },
                }
            )

        assert len(dispatcher.active_sessions) == 3
        for i in range(3):
            assert dispatcher.session_simulation_map[f"session-{i}"] == "sim-shared"
        # Only one subscription entry for the simulation
        assert "sim-shared" in dispatcher._simulation_subscriptions

    @pytest.mark.asyncio
    async def test_simulation_subscriptions_is_set(self):
        """_simulation_subscriptions should be a set tracking unique simulation IDs."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        assert isinstance(dispatcher._simulation_subscriptions, set)
        assert len(dispatcher._simulation_subscriptions) == 0

    @pytest.mark.asyncio
    async def test_session_simulation_map_is_dict(self):
        """session_simulation_map should be a dict mapping session_id to simulation_id."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        assert isinstance(dispatcher.session_simulation_map, dict)
        assert len(dispatcher.session_simulation_map) == 0


class TestDispatcherRelayChannelScoping:
    """Tests for C1: relay publishes to scoped channel when simulation_id is present."""

    def _make_dispatcher(self, agent_type: str = "runner_autopilot") -> RedisOrchestratorDispatcher:
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_relay_uses_scoped_channel_when_simulation_id_in_data(self):
        """Relay should publish to simulation:{sim_id}:broadcast when simulation_id is present."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        # Spawn a session so dispatcher owns it
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-owned",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-scoped"},
            }
        )

        # Create a mock Redis connection to capture the publish call
        mock_redis_conn = AsyncMock()
        mock_redis_conn.publish = AsyncMock()
        mock_redis_conn.aclose = AsyncMock()

        with patch("agents.utils.dispatcher.redis.from_url", return_value=mock_redis_conn):
            with patch.dict("os.environ", {"REDIS_ADDR": "redis://localhost:6379"}):
                # Broadcast targeting an unmatched session + our owned session
                await dispatcher._process_event(
                    {
                        "type": "broadcast",
                        "simulation_id": "sim-scoped",
                        "payload": {
                            "data": "TICK",
                            "targets": ["session-owned", "session-other-instance"],
                        },
                    }
                )

        # Verify relay was published to the scoped channel, not global
        mock_redis_conn.publish.assert_called_once()
        call_args = mock_redis_conn.publish.call_args
        relay_channel = call_args[0][0]
        assert relay_channel == "simulation:sim-scoped:broadcast", f"Expected scoped channel, got: {relay_channel}"

    @pytest.mark.asyncio
    async def test_relay_uses_global_channel_when_no_simulation_id(self):
        """Relay should publish to simulation:broadcast when no simulation_id is present."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        # Spawn a session without simulation_id
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-legacy",
                "payload": {"agentType": "runner_autopilot"},
            }
        )

        mock_redis_conn = AsyncMock()
        mock_redis_conn.publish = AsyncMock()
        mock_redis_conn.aclose = AsyncMock()

        with patch("agents.utils.dispatcher.redis.from_url", return_value=mock_redis_conn):
            with patch.dict("os.environ", {"REDIS_ADDR": "redis://localhost:6379"}):
                await dispatcher._process_event(
                    {
                        "type": "broadcast",
                        "payload": {
                            "data": "TICK",
                            "targets": ["session-legacy", "session-unknown"],
                        },
                    }
                )

        mock_redis_conn.publish.assert_called_once()
        call_args = mock_redis_conn.publish.call_args
        relay_channel = call_args[0][0]
        assert relay_channel == "simulation:broadcast", f"Expected global channel, got: {relay_channel}"

    @pytest.mark.asyncio
    async def test_relay_uses_payload_simulation_id_fallback(self):
        """Relay should check payload.simulation_id if top-level key is absent."""
        dispatcher = self._make_dispatcher("runner_autopilot")
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-x",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-payload"},
            }
        )

        mock_redis_conn = AsyncMock()
        mock_redis_conn.publish = AsyncMock()
        mock_redis_conn.aclose = AsyncMock()

        with patch("agents.utils.dispatcher.redis.from_url", return_value=mock_redis_conn):
            with patch.dict("os.environ", {"REDIS_ADDR": "redis://localhost:6379"}):
                await dispatcher._process_event(
                    {
                        "type": "broadcast",
                        "payload": {
                            "data": "TICK",
                            "simulation_id": "sim-payload",
                            "targets": ["session-x", "session-remote"],
                        },
                    }
                )

        mock_redis_conn.publish.assert_called_once()
        call_args = mock_redis_conn.publish.call_args
        relay_channel = call_args[0][0]
        assert relay_channel == "simulation:sim-payload:broadcast", (
            f"Expected scoped channel from payload fallback, got: {relay_channel}"
        )


class TestDispatcherSessionCleanup:
    """Tests for I1: remove_session() cleanup method."""

    def _make_dispatcher(self, agent_type: str = "runner_autopilot") -> RedisOrchestratorDispatcher:
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    def test_remove_session_clears_active_sessions(self):
        """remove_session should remove from active_sessions."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.add("session-1")

        dispatcher.remove_session("session-1")

        assert "session-1" not in dispatcher.active_sessions

    def test_remove_session_clears_simulation_map(self):
        """remove_session should remove from session_simulation_map."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.add("session-1")
        dispatcher.session_simulation_map["session-1"] = "sim-abc"
        dispatcher._simulation_subscriptions.add("sim-abc")

        dispatcher.remove_session("session-1")

        assert "session-1" not in dispatcher.session_simulation_map

    def test_remove_session_cleans_simulation_subscription_when_last(self):
        """When removing the last session for a simulation, clean up subscription."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.add("session-1")
        dispatcher.session_simulation_map["session-1"] = "sim-abc"
        dispatcher._simulation_subscriptions.add("sim-abc")

        dispatcher.remove_session("session-1")

        assert "sim-abc" not in dispatcher._simulation_subscriptions

    def test_remove_session_keeps_simulation_subscription_when_others_remain(self):
        """When other sessions remain for a simulation, keep the subscription."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.update({"session-1", "session-2"})
        dispatcher.session_simulation_map["session-1"] = "sim-abc"
        dispatcher.session_simulation_map["session-2"] = "sim-abc"
        dispatcher._simulation_subscriptions.add("sim-abc")

        dispatcher.remove_session("session-1")

        # session-2 still belongs to sim-abc
        assert "sim-abc" in dispatcher._simulation_subscriptions
        assert dispatcher.session_simulation_map["session-2"] == "sim-abc"

    def test_remove_session_noop_for_unknown_session(self):
        """Removing a non-existent session should not raise."""
        dispatcher = self._make_dispatcher()
        # Should not raise
        dispatcher.remove_session("nonexistent-session")
        assert len(dispatcher.active_sessions) == 0

    def test_remove_session_without_simulation_id(self):
        """Removing a session that has no simulation_id should work cleanly."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.add("session-legacy")

        dispatcher.remove_session("session-legacy")

        assert "session-legacy" not in dispatcher.active_sessions
        assert len(dispatcher.session_simulation_map) == 0

    def test_remove_multiple_sessions_different_simulations(self):
        """Removing sessions from different simulations cleans up independently."""
        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.update({"s1", "s2", "s3"})
        dispatcher.session_simulation_map["s1"] = "sim-a"
        dispatcher.session_simulation_map["s2"] = "sim-b"
        dispatcher.session_simulation_map["s3"] = "sim-a"
        dispatcher._simulation_subscriptions.update({"sim-a", "sim-b"})

        # Remove s2 — last session for sim-b
        dispatcher.remove_session("s2")
        assert "sim-b" not in dispatcher._simulation_subscriptions
        assert "sim-a" in dispatcher._simulation_subscriptions

        # Remove s1 — s3 still in sim-a
        dispatcher.remove_session("s1")
        assert "sim-a" in dispatcher._simulation_subscriptions

        # Remove s3 — last session for sim-a
        dispatcher.remove_session("s3")
        assert "sim-a" not in dispatcher._simulation_subscriptions
        assert len(dispatcher.active_sessions) == 0


class TestBroadcastSimulationScoping:
    """Tests that broadcasts with simulation_id only reach matching sessions."""

    def _make_dispatcher(self, agent_type="runner_autopilot"):
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_scoped_broadcast_only_triggers_matching_sessions(self):
        """A broadcast with simulation_id must only trigger sessions from that simulation."""
        dispatcher = self._make_dispatcher()
        triggered: list[str] = []
        dispatcher._trigger_agent_run = lambda session_id, content: triggered.append(session_id)

        # Spawn runners for two simulations
        for i in range(3):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"sim-a-runner-{i}",
                    "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-ALPHA"},
                }
            )
        for i in range(3):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"sim-b-runner-{i}",
                    "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-BETA"},
                }
            )

        assert len(dispatcher.active_sessions) == 6

        # Broadcast for sim-ALPHA only
        await dispatcher._process_event(
            {
                "type": "broadcast",
                "simulation_id": "sim-ALPHA",
                "payload": {"data": "TICK"},
            }
        )

        assert sorted(triggered) == ["sim-a-runner-0", "sim-a-runner-1", "sim-a-runner-2"]
        # sim-b runners must NOT be triggered
        for sid in triggered:
            assert sid.startswith("sim-a-"), f"Unexpected session triggered: {sid}"

    @pytest.mark.asyncio
    async def test_scoped_broadcast_does_not_trigger_other_simulation(self):
        """Broadcast for sim-B must NOT trigger any sim-A runners."""
        dispatcher = self._make_dispatcher()
        triggered: list[str] = []
        dispatcher._trigger_agent_run = lambda session_id, content: triggered.append(session_id)

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "sim-a-only",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-ALPHA"},
            }
        )
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "sim-b-only",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-BETA"},
            }
        )

        await dispatcher._process_event(
            {
                "type": "broadcast",
                "simulation_id": "sim-BETA",
                "payload": {"data": "TICK"},
            }
        )

        assert triggered == ["sim-b-only"]

    @pytest.mark.asyncio
    async def test_unscoped_broadcast_triggers_all(self):
        """A broadcast WITHOUT simulation_id should trigger all sessions (backward compat)."""
        dispatcher = self._make_dispatcher()
        triggered: list[str] = []
        dispatcher._trigger_agent_run = lambda session_id, content: triggered.append(session_id)

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "s1",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
            }
        )
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "s2",
                "payload": {"agentType": "runner_autopilot"},
            }
        )

        await dispatcher._process_event(
            {
                "type": "broadcast",
                "payload": {"data": "GLOBAL"},
            }
        )

        assert sorted(triggered) == ["s1", "s2"]


class TestEndSimulationLifecycle:
    """Tests that end_simulation removes all sessions for a simulation."""

    def _make_dispatcher(self, agent_type="runner_autopilot"):
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_end_simulation_removes_all_sessions(self):
        """end_simulation should remove all sessions for that simulation."""
        from agents.utils import simulation_registry

        await simulation_registry.clear()

        dispatcher = self._make_dispatcher()
        dispatcher._trigger_agent_run = MagicMock()

        for i in range(5):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"runner-{i}",
                    "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-DONE"},
                }
            )

        assert len(dispatcher.active_sessions) == 5

        await dispatcher._process_event(
            {
                "type": "end_simulation",
                "simulation_id": "sim-DONE",
            }
        )

        assert len(dispatcher.active_sessions) == 0
        assert len(dispatcher.session_simulation_map) == 0
        for i in range(5):
            assert await simulation_registry.lookup(f"runner-{i}") is None

    @pytest.mark.asyncio
    async def test_end_simulation_only_removes_matching_sessions(self):
        """end_simulation must NOT remove sessions from other simulations."""
        dispatcher = self._make_dispatcher()
        dispatcher._trigger_agent_run = MagicMock()

        for i in range(3):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"keep-{i}",
                    "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-KEEP"},
                }
            )
        for i in range(3):
            await dispatcher._process_event(
                {
                    "type": "spawn_agent",
                    "sessionId": f"remove-{i}",
                    "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-DONE"},
                }
            )

        assert len(dispatcher.active_sessions) == 6

        await dispatcher._process_event(
            {
                "type": "end_simulation",
                "simulation_id": "sim-DONE",
            }
        )

        assert len(dispatcher.active_sessions) == 3
        for i in range(3):
            assert f"keep-{i}" in dispatcher.active_sessions
            assert f"remove-{i}" not in dispatcher.active_sessions

    @pytest.mark.asyncio
    async def test_end_simulation_without_id_is_noop(self):
        """end_simulation without simulation_id should be ignored."""
        dispatcher = self._make_dispatcher()
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "s1",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-A"},
            }
        )

        await dispatcher._process_event(
            {
                "type": "end_simulation",
            }
        )

        assert "s1" in dispatcher.active_sessions

    @pytest.mark.asyncio
    async def test_broadcast_after_end_simulation_does_not_trigger_removed(self):
        """After end_simulation, a new broadcast must NOT trigger the removed sessions."""
        dispatcher = self._make_dispatcher()
        triggered: list[str] = []
        dispatcher._trigger_agent_run = lambda session_id, content: triggered.append(session_id)

        # Spawn sim-A (will end) and sim-B (will persist)
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "ended-runner",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-ENDED"},
            }
        )
        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "active-runner",
                "payload": {"agentType": "runner_autopilot", "simulation_id": "sim-ACTIVE"},
            }
        )

        # End sim-ENDED
        await dispatcher._process_event(
            {
                "type": "end_simulation",
                "simulation_id": "sim-ENDED",
            }
        )

        # Broadcast for sim-ACTIVE
        await dispatcher._process_event(
            {
                "type": "broadcast",
                "simulation_id": "sim-ACTIVE",
                "payload": {"data": "TICK"},
            }
        )

        assert triggered == ["active-runner"]


class TestDispatcherRegistryIntegration:
    """Tests for simulation_registry integration with dispatcher."""

    def _make_dispatcher(self, agent_type: str = "runner_autopilot") -> RedisOrchestratorDispatcher:
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    def setup_method(self):
        """Clear registry before each test."""
        from agents.utils.simulation_registry import _local

        _local.clear()

    @pytest.mark.asyncio
    async def test_spawn_registers_in_simulation_registry(self):
        """spawn_agent with simulation_id should register in simulation_registry."""
        from agents.utils.simulation_registry import lookup

        dispatcher = self._make_dispatcher()
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-reg-1",
                "payload": {
                    "agentType": "runner_autopilot",
                    "simulation_id": "sim-reg-abc",
                },
            }
        )

        assert await lookup("session-reg-1") == "sim-reg-abc"

    @pytest.mark.asyncio
    async def test_spawn_without_simulation_id_does_not_register(self):
        """spawn_agent without simulation_id should not register in simulation_registry."""
        from agents.utils.simulation_registry import lookup

        dispatcher = self._make_dispatcher()
        dispatcher._trigger_agent_run = MagicMock()

        await dispatcher._process_event(
            {
                "type": "spawn_agent",
                "sessionId": "session-noreg",
                "payload": {"agentType": "runner_autopilot"},
            }
        )

        assert await lookup("session-noreg") is None

    @pytest.mark.asyncio
    async def test_remove_session_unregisters_from_registry(self):
        """remove_session should unregister from simulation_registry."""
        from agents.utils.simulation_registry import lookup, register

        dispatcher = self._make_dispatcher()
        dispatcher.active_sessions.add("session-rm")
        dispatcher.session_simulation_map["session-rm"] = "sim-rm"
        dispatcher._simulation_subscriptions.add("sim-rm")
        await register("session-rm", "sim-rm")

        dispatcher.remove_session("session-rm")

        assert await lookup("session-rm") is None

    @pytest.mark.asyncio
    async def test_environment_reset_clears_registry(self):
        """environment_reset should clear the simulation_registry."""
        from agents.utils.simulation_registry import lookup, register

        dispatcher = self._make_dispatcher()
        await register("session-env-1", "sim-env")
        await register("session-env-2", "sim-env")

        await dispatcher._process_event({"type": "environment_reset"})

        assert await lookup("session-env-1") is None
        assert await lookup("session-env-2") is None


class TestCallableSpawnDelivery:
    """Verify that callable agents properly spawn all N sessions when
    delivered via HTTP (the gateway pokes once per session)."""

    def _make_dispatcher(self, agent_type: str = "planner_with_memory") -> RedisOrchestratorDispatcher:
        mock_runner = MagicMock()
        mock_runner.app.name = agent_type
        mock_runner.app.root_agent.name = f"{agent_type}_agent"
        return RedisOrchestratorDispatcher(runner=mock_runner, redis_url="redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_all_sessions_spawned_via_http_events(self):
        """When N spawn events arrive via handle_event(), all N sessions are added."""
        dispatcher = self._make_dispatcher()

        session_ids = [f"session-{i}" for i in range(5)]

        for sid in session_ids:
            await dispatcher.handle_event(
                {
                    "type": "spawn_agent",
                    "sessionId": sid,
                    "eventId": f"evt-{sid}",
                    "payload": {"agentType": "planner_with_memory"},
                }
            )

        assert len(dispatcher.active_sessions) == 5
        for sid in session_ids:
            assert sid in dispatcher.active_sessions

    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_http_spawned_sessions(self):
        """A broadcast targeting all N HTTP-spawned sessions reaches all of them."""
        dispatcher = self._make_dispatcher()

        session_ids = [f"session-{i}" for i in range(5)]

        # Spawn all 5
        for sid in session_ids:
            await dispatcher.handle_event(
                {
                    "type": "spawn_agent",
                    "sessionId": sid,
                    "eventId": f"evt-{sid}",
                    "payload": {"agentType": "planner_with_memory"},
                }
            )

        # Track which sessions get triggered
        triggered: list[str] = []
        dispatcher._trigger_agent_run = lambda session_id, content: triggered.append(session_id)

        await dispatcher.handle_event(
            {
                "type": "broadcast",
                "eventId": "broadcast-1",
                "payload": {
                    "data": '{"text":"simulate"}',
                    "targets": session_ids,
                },
            }
        )

        assert sorted(triggered) == sorted(session_ids)
