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

"""Tests for direct-write collection: runners RPUSH tick results to Redis.

Direct-write eliminates the RaceCollector PubSub bottleneck by having runners
write their process_tick results directly to the collector's Redis LIST.
"""

import importlib.util
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.utils.runner_protocol import build_tick_event, serialize_runner_event


def _make_clock(step: float = 0.2):
    """Return a callable that increments by *step* on each call."""
    t = [0.0]

    def _clock() -> float:
        val = t[0]
        t[0] += step
        return val

    return _clock


# Dynamic import since the skill directory is hyphenated
_tools_path = pathlib.Path(__file__).parents[1] / "skills" / "advancing-race-ticks" / "tools.py"
_spec = importlib.util.spec_from_file_location("race_tick.tools", _tools_path)
assert _spec is not None and _spec.loader is not None
tools_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools_module)
advance_tick = tools_module.advance_tick


def _make_tool_context(state=None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.session = MagicMock()
    ctx.session.id = "sim-session-1"
    ctx.invocation_id = "inv-001"
    ctx.agent_name = "tick-agent"
    ctx.actions = MagicMock()
    ctx.actions.escalate = False
    return ctx


class TestTickEventCollectorKey:
    """Tick events carry collector_buffer_key for direct-write collection."""

    def test_tick_event_includes_collector_buffer_key(self):
        event = build_tick_event(
            tick=5,
            max_ticks=6,
            total_race_hours=6.0,
            collector_buffer_key="collector:buffer:sim-1",
        )
        assert event.data["collector_buffer_key"] == "collector:buffer:sim-1"

    def test_tick_event_serializes_collector_buffer_key(self):
        event = build_tick_event(
            tick=5,
            max_ticks=6,
            total_race_hours=6.0,
            collector_buffer_key="collector:buffer:sim-1",
        )
        serialized = serialize_runner_event(event)
        parsed = json.loads(serialized)
        assert parsed["collector_buffer_key"] == "collector:buffer:sim-1"


class TestAdvanceTickPassesCollectorKey:
    """advance_tick should include collector_buffer_key in broadcast."""

    @pytest.mark.asyncio
    async def test_broadcast_includes_collector_buffer_key(self):
        mock_collector = MagicMock()
        mock_collector.drain = AsyncMock(return_value=[])

        state = {
            "current_tick": 0,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 10,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": [],
            "simulation_id": "sim-abc",
        }
        ctx = _make_tool_context(state=state)

        mock_publish = AsyncMock()
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", mock_publish),
        ):
            await advance_tick(tool_context=ctx)

        published_data = mock_publish.call_args[0][0]
        parsed = json.loads(published_data)
        assert parsed.get("collector_buffer_key") == "collector:buffer:sim-session-1"


class TestProcessTickDirectWrite:
    """process_tick should RPUSH result directly to collector buffer."""

    @pytest.mark.asyncio
    async def test_process_tick_rpushes_to_collector_buffer(self):
        """When collector_buffer_key is provided, process_tick RPUSHes result."""
        from agents.runner.running import process_tick

        mock_redis = AsyncMock()
        ctx = MagicMock()
        ctx.state = {
            "velocity": 1.0,
            "distance": 5.0,
            "water": 80.0,
            "exhausted": False,
            "collapsed": False,
            "finished": False,
            "hydration_efficiency": 1.0,
        }
        ctx.session = MagicMock()
        ctx.session.id = "runner-42"

        with patch(
            "agents.runner.running.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await process_tick(
                minutes_per_tick=30.0,
                elapsed_minutes=60.0,
                race_distance_mi=26.2188,
                tick=2,
                tool_context=ctx,
                inner_thought="",
                collector_buffer_key="collector:buffer:sim-1",
            )

        assert result["status"] == "success"
        # Verify RPUSH was called with the correct key
        mock_redis.rpush.assert_called_once()
        call_args = mock_redis.rpush.call_args
        assert call_args[0][0] == "collector:buffer:sim-1"
        # Verify the pushed data contains session_id and process_tick payload
        pushed_data = json.loads(call_args[0][1])
        assert pushed_data["session_id"] == "runner-42"
        assert pushed_data["payload"]["tool_name"] == "process_tick"
        assert pushed_data["payload"]["result"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_process_tick_skips_rpush_without_key(self):
        """When collector_buffer_key is empty, no RPUSH occurs."""
        from agents.runner.running import process_tick

        mock_redis = AsyncMock()
        ctx = MagicMock()
        ctx.state = {
            "velocity": 1.0,
            "distance": 5.0,
            "water": 80.0,
            "exhausted": False,
            "collapsed": False,
            "finished": False,
            "hydration_efficiency": 1.0,
        }
        ctx.session = MagicMock()
        ctx.session.id = "runner-42"

        with patch(
            "agents.runner.running.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await process_tick(
                minutes_per_tick=30.0,
                elapsed_minutes=60.0,
                race_distance_mi=26.2188,
                tick=2,
                tool_context=ctx,
                inner_thought="",
            )

        assert result["status"] == "success"
        mock_redis.rpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_tick_sets_buffer_ttl(self):
        """After RPUSH, process_tick should set 600s TTL on the buffer key."""
        from agents.runner.running import process_tick

        mock_redis = AsyncMock()
        ctx = MagicMock()
        ctx.state = {
            "velocity": 1.0,
            "distance": 5.0,
            "water": 80.0,
            "exhausted": False,
            "collapsed": False,
            "finished": False,
            "hydration_efficiency": 1.0,
        }
        ctx.session = MagicMock()
        ctx.session.id = "runner-42"

        with patch(
            "agents.runner.running.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await process_tick(
                minutes_per_tick=30.0,
                elapsed_minutes=60.0,
                race_distance_mi=26.2188,
                tick=2,
                tool_context=ctx,
                inner_thought="",
                collector_buffer_key="collector:buffer:sim-1",
            )

        assert result["status"] == "success"
        # Verify RPUSH was called
        mock_redis.rpush.assert_called_once()
        # Verify expire was called with buffer key and 7200s TTL
        mock_redis.expire.assert_called_once_with("collector:buffer:sim-1", 7200)

    @pytest.mark.asyncio
    async def test_process_tick_survives_redis_error(self):
        """RPUSH failure must not break process_tick -- result still returned."""
        from agents.runner.running import process_tick

        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock(side_effect=Exception("Redis down"))
        ctx = MagicMock()
        ctx.state = {
            "velocity": 1.0,
            "distance": 5.0,
            "water": 80.0,
            "exhausted": False,
            "collapsed": False,
            "finished": False,
            "hydration_efficiency": 1.0,
        }
        ctx.session = MagicMock()
        ctx.session.id = "runner-42"

        with patch(
            "agents.runner.running.get_shared_redis_client",
            return_value=mock_redis,
        ):
            result = await process_tick(
                minutes_per_tick=30.0,
                elapsed_minutes=60.0,
                race_distance_mi=26.2188,
                tick=2,
                tool_context=ctx,
                inner_thought="",
                collector_buffer_key="collector:buffer:sim-1",
            )

        # Must still return valid result despite Redis failure
        assert result["status"] == "success"


class TestTickCountOffByOne:
    """60s / 10s = 6 ticks. compile_results must report 6."""

    @pytest.mark.asyncio
    async def test_six_ticks_produce_six_snapshots(self):
        """With max_ticks=6 and current_tick starting at 0, we get 6 snapshots."""
        mock_collector = MagicMock()
        # Each drain returns one runner reporting
        runner_msg = {
            "session_id": "runner-1",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running",
                    "velocity": 1.0,
                    "distance_mi": 5.0,
                    "water": 80.0,
                },
            },
        }
        mock_collector.drain = AsyncMock(return_value=[runner_msg])

        state = {
            "current_tick": 0,  # Must start at 0, not 1
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1"],
        }
        ctx = _make_tool_context(state=state)

        # Run advance_tick 6 times (simulating the LoopAgent)
        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            for _ in range(6):
                await advance_tick(tool_context=ctx)

        assert len(ctx.state["tick_snapshots"]) == 6
        assert ctx.state["current_tick"] == 6

    @pytest.mark.asyncio
    async def test_advance_tick_flushes_stale_before_broadcast(self):
        """advance_tick should drain stale messages before broadcasting.

        START_GUN results can contaminate the collector buffer. A pre-drain
        flush discards them so only real tick results are aggregated.
        """
        mock_collector = MagicMock()
        # First drain returns stale START_GUN result (zero distance)
        stale_msg = {
            "session_id": "runner-1",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running",
                    "velocity": 1.0,
                    "distance_mi": 0.0,  # START_GUN: zero distance
                    "water": 100.0,
                },
            },
        }
        # Second drain returns real tick result (non-zero distance)
        real_msg = {
            "session_id": "runner-1",
            "payload": {
                "tool_name": "process_tick",
                "result": {
                    "status": "success",
                    "runner_status": "running",
                    "velocity": 1.0,
                    "distance_mi": 5.0,  # Real tick: actual distance
                    "water": 90.0,
                },
            },
        }
        # drain() called: 1st = pre-flush (stale), 2nd = zero-interval drain (real)
        mock_collector.drain = AsyncMock(side_effect=[[stale_msg], [real_msg]])

        state = {
            "current_tick": 0,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0,
                "total_race_hours": 6.0,
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1"],
        }
        ctx = _make_tool_context(state=state)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
        ):
            result = await advance_tick(tool_context=ctx)

        # Should aggregate the REAL result (5.0 mi), not the stale one (0.0 mi)
        assert result["avg_distance"] == 5.0, (
            f"Expected avg_distance=5.0 (real tick), got {result['avg_distance']} "
            f"(stale START_GUN result was not flushed)"
        )


class TestOptimizedPolling:
    """advance_tick should use 200ms poll interval by default."""

    @pytest.mark.asyncio
    async def test_default_poll_interval_is_200ms(self):
        """Default poll_interval should be 0.2s (200ms), not the old 0.05s."""
        mock_collector = MagicMock()
        first_batch = [
            {
                "session_id": "runner-1",
                "payload": {
                    "tool_name": "process_tick",
                    "result": {
                        "status": "success",
                        "runner_status": "running",
                        "velocity": 1.0,
                        "distance_mi": 5.0,
                        "water": 80.0,
                    },
                },
            }
        ]
        # drain calls: 1st = pre-flush, 2nd = early-wake (empty),
        # 3rd = early-wake (empty), 4th = post-sleep poll (data)
        mock_collector.drain = AsyncMock(side_effect=[[], [], [], first_batch])

        state = {
            "current_tick": 0,
            "max_ticks": 6,
            "simulation_config": {
                "tick_interval_seconds": 0.4,
                "total_race_hours": 6.0,
                "max_collection_seconds": 2.0,
                # NOTE: no explicit poll_interval set -- should default to 0.2
            },
            "tick_snapshots": [],
            "runner_session_ids": ["runner-1"],
        }
        ctx = _make_tool_context(state=state)

        sleep_calls = []

        async def mock_sleep(s):
            sleep_calls.append(s)

        with (
            patch(
                "agents.simulator.collector.RaceCollector.get",
                return_value=mock_collector,
            ),
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch.object(tools_module, "publish_to_runners", AsyncMock()),
            patch.object(tools_module.time, "perf_counter", _make_clock(step=0.2)),
        ):
            await advance_tick(tool_context=ctx)

        # Post-sleep poll uses poll_interval=0.2 (the new default)
        poll_sleeps = [s for s in sleep_calls if s == pytest.approx(0.2, abs=0.01)]
        assert len(poll_sleeps) >= 1, f"Expected 0.2s poll sleeps, got: {sleep_calls}"
        # No old 0.05 default
        old_sleeps = [s for s in sleep_calls if abs(s - 0.05) < 0.01]
        assert len(old_sleeps) == 0, f"Found old 0.05 poll intervals: {sleep_calls}"
