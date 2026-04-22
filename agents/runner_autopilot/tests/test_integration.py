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

"""Integration tests for runner_autopilot using InMemoryRunner.

These tests exercise the full agent pipeline through ADK's InMemoryRunner:
structured message -> callback interception -> tool execution -> state
changes -> summary response.

No LLM mocking needed — the before_model_callback intercepts all model
calls and returns deterministic LlmResponse objects.
"""

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.runner_autopilot.agent import root_agent
from agents.utils.runner_protocol import RunnerEvent, RunnerEventType, serialize_runner_event


APP_NAME = "test_autopilot"


def _msg(event_type: RunnerEventType, **data) -> types.Content:
    """Build a user message Content from a RunnerEvent."""
    text = serialize_runner_event(RunnerEvent(event=event_type, data=data))
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


async def _collect_events(runner: InMemoryRunner, user_id: str, session_id: str, message: types.Content) -> list:
    """Run the agent and collect all emitted events."""
    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        events.append(event)
    return events


def _final_text(events: list) -> str:
    """Extract concatenated text from the final event's content parts."""
    final = events[-1]
    if not final.content or not final.content.parts:
        return ""
    return "".join(p.text for p in final.content.parts if p.text)


def _has_function_call(events: list, func_name: str) -> bool:
    """Check if any event in the stream contains a function call with the given name."""
    for event in events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call and part.function_call.name == func_name:
                return True
    return False


def _has_function_response(events: list, func_name: str) -> bool:
    """Check if any event in the stream contains a function response for the given name."""
    for event in events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_response and part.function_response.name == func_name:
                return True
    return False


# ---------------------------------------------------------------------------
# Test: start_gun event
# ---------------------------------------------------------------------------


class TestStartGun:
    @pytest.mark.asyncio
    async def test_does_not_initialize_runner(self):
        """start_gun should NOT initialize runner state -- that's tick 0's job."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        session_id = "s_start"
        await runner.session_service.create_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            session_id,
            _msg(RunnerEventType.START_GUN),
        )

        assert len(events) >= 1, f"Expected >=1 events, got {len(events)}"
        # Verify runner state was NOT initialized (deferred to tick 0)
        session = await runner.session_service.get_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
        )
        assert session is not None
        assert session.state.get("velocity") is None

    @pytest.mark.asyncio
    async def test_produces_text_acknowledgement(self):
        """start_gun should return text acknowledgement (no process_tick call)."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_start_text",
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_start_text",
            _msg(RunnerEventType.START_GUN),
        )

        text = _final_text(events)
        assert text, "Expected non-empty text in final event"
        assert not _has_function_call(events, "process_tick"), "start_gun should NOT trigger process_tick"


# ---------------------------------------------------------------------------
# Test: tick event
# ---------------------------------------------------------------------------


class TestTick:
    @pytest.mark.asyncio
    async def test_triggers_process_tick_tool(self):
        """tick should trigger process_tick tool for a running runner."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_tick",
            app_name=APP_NAME,
            state={
                "velocity": 1.0,
                "distance": 0.0,
                "water": 100.0,
                "finished": False,
                "collapsed": False,
                "will_hit_wall": False,
                "wall_mi": 18.6411,
                "wall_severity": 0.0,
                "hydration_efficiency": 1.0,
            },
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_tick",
            _msg(
                RunnerEventType.TICK,
                tick=1,
                max_ticks=24,
                minutes_per_tick=15.0,
                elapsed_minutes=15.0,
                race_distance_mi=26.2188,
            ),
        )

        assert _has_function_call(events, "process_tick"), "Expected process_tick function call in events"
        assert _has_function_response(events, "process_tick"), "Expected function response for process_tick"

    @pytest.mark.asyncio
    async def test_tick_advances_distance(self):
        """After a tick, runner distance should be non-zero."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        session_id = "s_tick_dist"
        await runner.session_service.create_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
            state={
                "velocity": 1.0,
                "distance": 0.0,
                "water": 100.0,
                "finished": False,
                "collapsed": False,
                "will_hit_wall": False,
                "wall_mi": 18.6411,
                "wall_severity": 0.0,
                "hydration_efficiency": 1.0,
            },
        )
        await _collect_events(
            runner,
            "u1",
            session_id,
            _msg(
                RunnerEventType.TICK,
                tick=1,
                max_ticks=24,
                minutes_per_tick=15.0,
                elapsed_minutes=15.0,
                race_distance_mi=26.2188,
            ),
        )
        session = await runner.session_service.get_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
        )
        assert session is not None
        assert session.state["distance"] > 0.0

    @pytest.mark.asyncio
    async def test_finished_runner_still_calls_process_tick(self):
        """Finished runners must still call process_tick for telemetry reporting.

        Regression: previously handle_tick returned text for finished runners,
        which caused advance_tick aggregation to skip them entirely, dropping
        runners_reporting to zero once all runners finished.
        """
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_tick_finished",
            app_name=APP_NAME,
            state={
                "velocity": 1.0,
                "distance": 26.2188,
                "water": 50.0,
                "finished": True,
                "collapsed": False,
                "will_hit_wall": False,
                "wall_mi": 18.6411,
                "wall_severity": 0.0,
                "hydration_efficiency": 1.0,
            },
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_tick_finished",
            _msg(
                RunnerEventType.TICK,
                tick=20,
                max_ticks=24,
                minutes_per_tick=15.0,
                elapsed_minutes=300.0,
                race_distance_mi=26.2188,
            ),
        )

        assert _has_function_call(events, "process_tick"), "Finished runners must still call process_tick for telemetry"
        assert _has_function_response(events, "process_tick"), (
            "Expected function response for process_tick from finished runner"
        )


# ---------------------------------------------------------------------------
# Test: unknown / malformed events
# ---------------------------------------------------------------------------


class TestUnknownEvent:
    @pytest.mark.asyncio
    async def test_random_text_does_not_crash(self):
        """Random gibberish should produce a text response, not crash."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_unknown",
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_unknown",
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="random gibberish")],
            ),
        )

        assert len(events) >= 1, "Expected at least 1 event for unknown input"
        text = _final_text(events)
        assert text, "Expected non-empty text response for unknown event"

    @pytest.mark.asyncio
    async def test_empty_json_does_not_crash(self):
        """An empty JSON object (no 'event' key) should not crash."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_empty_json",
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_empty_json",
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="{}")],
            ),
        )

        assert len(events) >= 1


# ---------------------------------------------------------------------------
# Test: crowd_boost event
# ---------------------------------------------------------------------------


class TestCrowdBoost:
    @pytest.mark.asyncio
    async def test_accelerates_with_given_intensity(self):
        """crowd_boost should trigger accelerate with the specified intensity."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_crowd",
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_crowd",
            _msg(RunnerEventType.CROWD_BOOST, intensity=0.8),
        )

        assert _has_function_call(events, "accelerate"), "Expected accelerate call for crowd_boost"
        # Should end with a summary
        text = _final_text(events)
        assert text, "Expected summary text after crowd_boost"


# ---------------------------------------------------------------------------
# Test: distance_update event
# ---------------------------------------------------------------------------


class TestDistanceUpdate:
    @pytest.mark.asyncio
    async def test_distance_update_is_noop(self):
        """distance_update must NOT trigger deplete_water for autopilot runners.

        Regression: process_tick already handles water depletion internally.
        Frontend distance_update events caused double depletion and universal
        runner collapse.
        """
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_dist",
            app_name=APP_NAME,
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_dist",
            _msg(RunnerEventType.DISTANCE_UPDATE, mi_delta=1.0),
        )

        assert not _has_function_call(events, "deplete_water"), (
            "distance_update must NOT call deplete_water -- process_tick handles depletion"
        )
        text = _final_text(events)
        assert text, "Expected text acknowledgment from distance_update no-op"


# ---------------------------------------------------------------------------
# Test: hydration_station event (with low water to guarantee rehydrate)
# ---------------------------------------------------------------------------


class TestHydrationStation:
    @pytest.mark.asyncio
    async def test_rehydrates_when_exhausted(self):
        """hydration_station with exhausted state should always rehydrate."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        # Initialize session with low water and exhausted state
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_hydrate",
            app_name=APP_NAME,
            state={
                "water": 20.0,
                "exhausted": True,
                "velocity": 0.0,
                "distance": 5.0,
            },
        )
        events = await _collect_events(
            runner,
            "u1",
            "s_hydrate",
            _msg(RunnerEventType.HYDRATION_STATION),
        )

        assert _has_function_call(events, "rehydrate"), "Expected rehydrate call when exhausted at hydration station"


# ---------------------------------------------------------------------------
# Test: sequential messages in same session
# ---------------------------------------------------------------------------


class TestSequentialMessages:
    @pytest.mark.asyncio
    async def test_start_then_tick(self):
        """Send start_gun then tick in the same session."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        await runner.session_service.create_session(
            user_id="u1",
            session_id="s_seq",
            app_name=APP_NAME,
        )

        # First: start_gun (initializes runner profile, returns text)
        events1 = await _collect_events(
            runner,
            "u1",
            "s_seq",
            _msg(RunnerEventType.START_GUN),
        )
        text = _final_text(events1)
        assert text, "Expected text response from start_gun"

        # Second: tick (now triggers process_tick tool)
        events2 = await _collect_events(
            runner,
            "u1",
            "s_seq",
            _msg(
                RunnerEventType.TICK,
                tick=1,
                max_ticks=24,
                minutes_per_tick=15.0,
                elapsed_minutes=15.0,
                race_distance_mi=26.2188,
            ),
        )
        assert _has_function_call(events2, "process_tick"), "Expected process_tick after start_gun + tick"

    @pytest.mark.asyncio
    async def test_start_then_multiple_ticks_advance_distance(self):
        """Multiple ticks should steadily increase distance."""
        runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
        session_id = "s_seq_multi"
        await runner.session_service.create_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
        )

        # Start gun
        await _collect_events(
            runner,
            "u1",
            session_id,
            _msg(RunnerEventType.START_GUN),
        )

        # Two ticks
        for tick in range(2):
            await _collect_events(
                runner,
                "u1",
                session_id,
                _msg(
                    RunnerEventType.TICK,
                    tick=tick,
                    max_ticks=24,
                    minutes_per_tick=15.0,
                    elapsed_minutes=(tick + 1) * 15.0,
                    race_distance_mi=26.2188,
                ),
            )

        session = await runner.session_service.get_session(
            user_id="u1",
            session_id=session_id,
            app_name=APP_NAME,
        )
        assert session is not None
        assert session.state["distance"] > 0.0
        assert session.state["water"] < 100.0
