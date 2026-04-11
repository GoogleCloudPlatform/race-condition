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

"""Integration tests for the concurrency benchmark."""

import pytest

from scripts.bench.bench_concurrency import (
    load_agent,
    run_level,
    LevelResult,
)


class TestLoadAgent:
    def test_loads_runner_autopilot(self):
        agent = load_agent("agents.npc.runner_autopilot.agent")
        assert agent.name == "runner_autopilot"

    def test_raises_for_missing_module(self):
        with pytest.raises((ImportError, ModuleNotFoundError)):
            load_agent("nonexistent.module")

    def test_raises_for_no_root_agent(self):
        with pytest.raises(AttributeError):
            load_agent("scripts.bench.bench_helpers")  # module without root_agent


class TestRunLevel:
    @pytest.mark.asyncio
    async def test_small_scale_inmemory(self):
        """Run 5 concurrent sessions with InMemoryRunner to verify pipeline."""
        from google.adk.runners import InMemoryRunner

        from agents.npc.runner_autopilot.agent import root_agent

        runner = InMemoryRunner(agent=root_agent, app_name="bench_test")

        # Pre-create sessions
        session_ids = []
        for i in range(5):
            sid = f"bench_test_{i}"
            await runner.session_service.create_session(
                user_id="bench",
                session_id=sid,
                app_name="bench_test",
            )
            session_ids.append(sid)

        result = await run_level(
            runner=runner,
            app_name="bench_test",
            session_ids=session_ids,
            prompt='{"event":"start_gun"}',
        )

        assert isinstance(result, LevelResult)
        assert result.n == 5
        assert result.throughput > 0
        assert result.p50 > 0
        assert result.p95 >= result.p50
        assert result.p99 >= result.p95
        assert result.errors == 0
        assert len(result.latencies) == 5

    @pytest.mark.asyncio
    async def test_handles_tick_event(self):
        """Verify benchmark works with tick events after start_gun."""
        from google.adk.runners import InMemoryRunner

        from agents.npc.runner_autopilot.agent import root_agent

        runner = InMemoryRunner(agent=root_agent, app_name="bench_tick")

        sid = "bench_tick_0"
        await runner.session_service.create_session(
            user_id="bench",
            session_id=sid,
            app_name="bench_tick",
        )

        # First send start_gun to initialize
        result_init = await run_level(
            runner=runner,
            app_name="bench_tick",
            session_ids=[sid],
            prompt='{"event":"start_gun"}',
        )
        assert result_init.errors == 0

        # Then send a tick
        tick_prompt = (
            '{"event":"tick","tick":1,"max_ticks":24,'
            '"minutes_per_tick":15.0,"elapsed_minutes":15.0,'
            '"race_distance_mi":26.2188}'
        )
        result_tick = await run_level(
            runner=runner,
            app_name="bench_tick",
            session_ids=[sid],
            prompt=tick_prompt,
        )
        assert result_tick.errors == 0
        assert result_tick.n == 1


class TestPrintResults:
    def test_print_results_does_not_crash(self, capsys):
        """Verify print_results handles valid data without errors."""
        from scripts.bench.bench_concurrency import print_results

        results = [
            LevelResult(
                n=10,
                throughput=100.0,
                p50=0.005,
                p95=0.010,
                p99=0.015,
                wall_time=0.1,
                memory_bytes=1024,
                errors=0,
                pool_status="5/40",
                latencies=[0.005] * 10,
            ),
        ]
        print_results(results, "test_agent", "pool_size=20, max_overflow=20 (max=40)")
        captured = capsys.readouterr()
        assert "test_agent" in captured.out
        assert "10" in captured.out
