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

"""End-to-end test for simulator-runner coordination.

Exercises the full runner lifecycle using InMemoryRunner: initialization
via START_GUN (with seeded log-normal distribution), per-tick physics
(distance, hydration, wall effect), finish detection, and DNF handling.

20 runners run through a simulated marathon. This test does NOT require
Redis -- it directly drives runners via InMemoryRunner and verifies the
aggregate behavior matches expectations.

Marked @pytest.mark.slow because it runs 20 runners through 24 ticks.
"""

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.npc.runner_autopilot.agent import root_agent as runner_agent
from agents.utils.runner_protocol import (
    RunnerEvent,
    RunnerEventType,
    serialize_runner_event,
)

RUNNER_COUNT = 20
MARATHON_MI = 26.2188
TOTAL_RACE_HOURS = 6.0
MAX_TICKS = 24
APP_NAME = "test_e2e_sim"


def _msg(event_type: RunnerEventType, **data) -> types.Content:
    """Build a user message Content from a RunnerEvent."""
    text = serialize_runner_event(RunnerEvent(event=event_type, data=data))
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


async def _run_agent(
    runner: InMemoryRunner,
    session_id: str,
    message: types.Content,
) -> list:
    """Run the agent and collect all emitted events."""
    events = []
    async for event in runner.run_async(
        user_id="sim",
        session_id=session_id,
        new_message=message,
    ):
        events.append(event)
    return events


@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_runner_lifecycle():
    """Run 20 runners through a marathon and verify coordination invariants.

    This test exercises:
    1. START_GUN initializes runners with varied velocities (log-normal)
    2. Each TICK advances distance, depletes hydration
    3. Some runners finish the marathon
    4. Distance increases monotonically for active runners
    5. Water decreases over time (with station bumps)
    6. Finished runners don't move further
    """
    minutes_per_tick = (TOTAL_RACE_HOURS * 60) / MAX_TICKS  # 15 min

    # --- Setup runners ---
    runner_sessions = [f"runner-e2e-{i:03d}" for i in range(RUNNER_COUNT)]
    runners: dict[str, InMemoryRunner] = {}
    for sid in runner_sessions:
        r = InMemoryRunner(agent=runner_agent, app_name=APP_NAME)
        await r.session_service.create_session(
            user_id="sim",
            session_id=sid,
            app_name=APP_NAME,
        )
        runners[sid] = r

    # --- Send START_GUN to all runners ---
    start_msg = _msg(RunnerEventType.START_GUN)
    velocities = []
    for sid, r in runners.items():
        await _run_agent(r, sid, start_msg)
        session = await r.session_service.get_session(
            user_id="sim",
            session_id=sid,
            app_name=APP_NAME,
        )
        assert session is not None
        v = session.state.get("velocity", 0)
        assert v > 0, f"Runner {sid} has zero velocity after START_GUN"
        velocities.append(v)

    # Verify velocity distribution has variation (not all identical)
    unique_velocities = set(round(v, 4) for v in velocities)
    assert len(unique_velocities) > 1, "All runners have identical velocity"

    # --- Run ticks ---
    per_runner_distances: dict[str, list[float]] = {sid: [0.0] for sid in runner_sessions}

    for tick in range(MAX_TICKS):
        elapsed = (tick + 1) * minutes_per_tick
        tick_msg = _msg(
            RunnerEventType.TICK,
            tick=tick,
            max_ticks=MAX_TICKS,
            minutes_per_tick=minutes_per_tick,
            elapsed_minutes=elapsed,
            race_distance_mi=MARATHON_MI,
        )

        for sid, r in runners.items():
            await _run_agent(r, sid, tick_msg)
            session = await r.session_service.get_session(
                user_id="sim",
                session_id=sid,
                app_name=APP_NAME,
            )
            assert session is not None
            per_runner_distances[sid].append(session.state.get("distance", 0.0))

    # --- Collect final states ---
    finished_runners = []
    dnf_runners = []
    collapsed_runners = []
    final_distances = []
    final_waters = []

    for sid, r in runners.items():
        session = await r.session_service.get_session(
            user_id="sim",
            session_id=sid,
            app_name=APP_NAME,
        )
        assert session is not None
        state = session.state

        final_distances.append(state.get("distance", 0.0))
        final_waters.append(state.get("water", 100.0))

        if state.get("finished"):
            finished_runners.append(sid)
            # Verify finish data
            assert state.get("finish_time_minutes") is not None, f"Runner {sid} finished but has no finish_time_minutes"
            assert state.get("pace_min_per_mi") is not None, f"Runner {sid} finished but has no pace_min_per_mi"
            assert state["pace_min_per_mi"] > 0
            assert state["finish_time_minutes"] > 0
        elif state.get("collapsed"):
            collapsed_runners.append(sid)
        else:
            dnf_runners.append(sid)

    # --- Assertions ---

    # 1. All runners should have non-zero distance
    for sid in runner_sessions:
        assert final_distances[runner_sessions.index(sid)] > 0, f"Runner {sid} has zero distance"

    # 2. Distance should be monotonically increasing for each runner
    for sid, distances in per_runner_distances.items():
        for i in range(1, len(distances)):
            assert distances[i] >= distances[i - 1], (
                f"Runner {sid} distance decreased: tick {i - 1}={distances[i - 1]}, tick {i}={distances[i]}"
            )

    # 3. Some runners should finish (with log-normal distribution, fast
    #    runners finish in ~2.5-4h, which is within our 6h simulation)
    assert len(finished_runners) > 0, (
        f"No runners finished. Max distance: {max(final_distances):.1f}mi. "
        f"Expected at least some to cover {MARATHON_MI}mi in {TOTAL_RACE_HOURS}h."
    )

    # 4. Average water should decrease (runners deplete hydration)
    avg_water = sum(final_waters) / len(final_waters)
    assert avg_water < 90.0, f"Average water {avg_water:.1f}% is too high -- hydration should deplete"

    # 5. Verify total counts add up
    assert len(finished_runners) + len(dnf_runners) + len(collapsed_runners) == RUNNER_COUNT

    # 6. Finished runners should not have moved after finishing
    for sid in finished_runners:
        distances = per_runner_distances[sid]
        # Find the tick where they finished
        for i in range(len(distances) - 1):
            if distances[i] >= MARATHON_MI:
                # All subsequent distances should be the same
                for j in range(i + 1, len(distances)):
                    assert distances[j] == distances[i], (
                        f"Finished runner {sid} moved after finishing: tick {i}={distances[i]}, tick {j}={distances[j]}"
                    )
                break
