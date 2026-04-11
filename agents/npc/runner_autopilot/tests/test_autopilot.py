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

from unittest.mock import MagicMock

from google.genai import types

from agents.npc.runner_autopilot.autopilot import (
    Phase,
    autopilot_callback,
    build_summary,
    detect_phase,
    extract_last_user_text,
    handle_crowd_boost,
    handle_distance_update,
    handle_hydration_station,
    handle_start_gun,
    handle_tick,
    initialize_runner,
)


def _make_request(*contents: types.Content) -> MagicMock:
    """Helper to build a mock LlmRequest with given contents."""
    req = MagicMock()
    req.contents = list(contents)
    return req


def _user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


def _function_response_content() -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part.from_function_response(
                name="accelerate",
                response={"status": "success", "velocity": 1.0},
            )
        ],
    )


def _get_fc(response: object) -> types.FunctionCall:
    """Extract the first function_call from an LlmResponse, asserting it exists."""
    content = getattr(response, "content", None)
    assert content is not None, "response.content is None"
    assert content.parts is not None, "content.parts is None"
    fc = content.parts[0].function_call
    assert fc is not None, "function_call is None"
    return fc


def _get_text(response: object) -> str:
    """Extract the first text part from an LlmResponse, asserting it exists."""
    content = getattr(response, "content", None)
    assert content is not None, "response.content is None"
    assert content.parts is not None, "content.parts is None"
    text = content.parts[0].text
    assert text is not None, "text is None"
    return text


class TestDetectPhase:
    def test_user_message_is_decide(self) -> None:
        req = _make_request(_user_content('{"event": "start_gun"}'))
        assert detect_phase(req) == Phase.DECIDE

    def test_function_response_is_summarize(self) -> None:
        req = _make_request(
            _user_content('{"event": "start_gun"}'),
            _function_response_content(),
        )
        assert detect_phase(req) == Phase.SUMMARIZE


class TestExtractLastUserText:
    def test_extracts_text(self) -> None:
        req = _make_request(_user_content("hello world"))
        assert extract_last_user_text(req) == "hello world"


class TestInitializeRunner:
    def test_sets_velocity_from_lognormal(self) -> None:
        state: dict = {}
        initialize_runner(state, "test-session-123")
        assert "velocity" in state
        assert state["velocity"] > 0

    def test_sets_wall_parameters(self) -> None:
        state: dict = {}
        initialize_runner(state, "test-session-123")
        assert "will_hit_wall" in state
        assert "wall_mi" in state
        assert "wall_severity" in state

    def test_deterministic_per_session_id(self) -> None:
        state1: dict = {}
        state2: dict = {}
        initialize_runner(state1, "same-id")
        initialize_runner(state2, "same-id")
        assert state1["velocity"] == state2["velocity"]
        assert state1["will_hit_wall"] == state2["will_hit_wall"]

    def test_different_sessions_get_different_values(self) -> None:
        state1: dict = {}
        state2: dict = {}
        initialize_runner(state1, "session-aaa")
        initialize_runner(state2, "session-bbb")
        # Statistically extremely unlikely to be identical
        assert state1["velocity"] != state2["velocity"] or state1["will_hit_wall"] != state2["will_hit_wall"]

    def test_sets_runner_status(self) -> None:
        state: dict = {}
        initialize_runner(state, "test-session")
        assert state["runner_status"] == "running"
        assert state["finished"] is False
        assert state["collapsed"] is False


class TestHandleStartGun:
    def test_returns_text_acknowledgement(self) -> None:
        """Start gun should return text acknowledgement, not process_tick."""
        state: dict = {}
        response = handle_start_gun(state, {"_session_id": "test-123"})
        _get_text(response)

    def test_does_not_initialize_runner(self) -> None:
        """Start gun should NOT initialize runner state -- that's tick 0's job."""
        state: dict = {}
        handle_start_gun(state, {"_session_id": "test-456"})
        assert state.get("velocity") is None
        assert state.get("finished") is None


class TestHandleCrowdBoost:
    def test_accelerates_with_given_intensity(self) -> None:
        state: dict = {}
        response = handle_crowd_boost(state, {"intensity": 0.8})
        fc = _get_fc(response)
        assert fc.name == "accelerate"
        assert fc.args is not None
        assert fc.args["intensity"] == 0.8

    def test_default_intensity(self) -> None:
        state: dict = {}
        response = handle_crowd_boost(state, {})
        fc = _get_fc(response)
        assert fc.args is not None
        assert fc.args["intensity"] == 0.5


class TestHandleDistanceUpdate:
    def test_is_noop_returns_text(self) -> None:
        """distance_update must be a no-op for autopilot runners.

        Regression: process_tick already handles water depletion internally.
        The frontend sends distance_update events on mile boundary crossings,
        which caused double depletion and universal runner collapse.
        """
        state = {"distance": 5.0}
        response = handle_distance_update(state, {"mi_delta": 1.0})
        text = _get_text(response)
        assert text, "Expected text response (no-op), not a function call"

    def test_noop_regardless_of_mi_delta(self) -> None:
        """Even with large mi_delta, distance_update must remain a no-op."""
        state = {"distance": 5.0}
        response = handle_distance_update(state, {"mi_delta": 10.0})
        text = _get_text(response)
        assert text, "Expected text response (no-op) for any mi_delta"


class TestHandleHydrationStation:
    def test_always_stop_when_low(self) -> None:
        state = {"water": 25, "exhausted": False}
        response = handle_hydration_station(state, {})
        fc = _get_fc(response)
        assert fc.name == "rehydrate"

    def test_always_stop_when_exhausted(self) -> None:
        state = {"water": 80, "exhausted": True}
        response = handle_hydration_station(state, {})
        fc = _get_fc(response)
        assert fc.name == "rehydrate"

    def test_always_stop_at_boundary(self) -> None:
        state = {"water": 40, "exhausted": False}
        response = handle_hydration_station(state, {})
        fc = _get_fc(response)
        assert fc.name == "rehydrate"

    def test_probabilistic_mid_range(self) -> None:
        state = {"water": 50, "exhausted": False}
        stops = 0
        trials = 1000
        for _ in range(trials):
            resp = handle_hydration_station(state, {})
            content = resp.content
            assert content is not None
            assert content.parts is not None
            if content.parts[0].function_call is not None:
                stops += 1
        assert 350 < stops < 650

    def test_probabilistic_high_range(self) -> None:
        state = {"water": 80, "exhausted": False}
        stops = 0
        trials = 1000
        for _ in range(trials):
            resp = handle_hydration_station(state, {})
            content = resp.content
            assert content is not None
            assert content.parts is not None
            if content.parts[0].function_call is not None:
                stops += 1
        assert 150 < stops < 450


class TestHandleTick:
    def test_initializes_runner_on_first_tick(self) -> None:
        """Tick 0 should initialize runner if velocity not yet set."""
        state: dict = {}
        response = handle_tick(
            state,
            {
                "_session_id": "test-init-tick",
                "tick": 0,
                "max_ticks": 6,
                "minutes_per_tick": 0.0,
                "elapsed_minutes": 0.0,
                "race_distance_mi": 26.2188,
            },
        )
        fc = _get_fc(response)
        assert fc.name == "process_tick"
        assert state["velocity"] > 0
        assert state["finished"] is False

    def test_does_not_reinitialize_on_subsequent_ticks(self) -> None:
        """Once initialized, handle_tick should not re-initialize."""
        state = {"velocity": 1.5, "finished": False, "collapsed": False}
        handle_tick(state, {"tick": 1, "max_ticks": 6, "minutes_per_tick": 60.0})
        assert state["velocity"] == 1.5  # unchanged

    def test_returns_process_tick_call_for_running_runner(self) -> None:
        state = {"velocity": 1.0, "finished": False, "collapsed": False}
        response = handle_tick(
            state,
            {
                "tick": 5,
                "max_ticks": 24,
                "minutes_per_tick": 15.0,
                "elapsed_minutes": 75.0,
                "race_distance_mi": 26.2188,
            },
        )
        fc = _get_fc(response)
        assert fc.name == "process_tick"

    def test_returns_process_tick_for_finished_runner(self) -> None:
        """Finished runners must still call process_tick for telemetry reporting."""
        state = {"velocity": 1.0, "finished": True, "collapsed": False}
        response = handle_tick(state, {"tick": 5, "max_ticks": 24})
        fc = _get_fc(response)
        assert fc.name == "process_tick"

    def test_returns_process_tick_for_collapsed_runner(self) -> None:
        """Collapsed runners must still call process_tick for telemetry reporting."""
        state = {"velocity": 1.0, "finished": False, "collapsed": True}
        response = handle_tick(state, {"tick": 5, "max_ticks": 24})
        fc = _get_fc(response)
        assert fc.name == "process_tick"


class TestBuildSummary:
    def test_returns_text(self) -> None:
        state = {"velocity": 5.0, "water": 80, "distance": 10.0, "exhausted": False}
        response = build_summary(state)
        _get_text(response)

    def test_summary_uses_miles_unit(self) -> None:
        state = {"velocity": 5.0, "water": 80, "distance": 10.0, "exhausted": False}
        response = build_summary(state)
        text = _get_text(response)
        assert "distance=10.0mi" in text, f"Expected 'mi' unit in summary, got: {text}"
        assert "km" not in text, f"Found 'km' in summary text: {text}"


class TestAutopilotCallback:
    def test_start_gun_returns_text_not_function_call(self) -> None:
        """Start gun should return text acknowledgement, not initialize runner."""
        ctx = MagicMock()
        ctx.state = {}
        ctx.session.id = "test-callback-session"
        req = _make_request(_user_content('{"event": "start_gun", "data": {"tick": 0}}'))
        response = autopilot_callback(ctx, req)
        _get_text(response)
        assert ctx.state.get("velocity") is None

    def test_start_gun_does_not_initialize_runner(self) -> None:
        """Start gun should NOT set velocity or runner state."""
        ctx = MagicMock()
        ctx.state = {}
        ctx.session.id = "test-init-session"
        req = _make_request(_user_content('{"event": "start_gun", "data": {"tick": 0}}'))
        autopilot_callback(ctx, req)
        assert ctx.state.get("velocity") is None
        assert ctx.state.get("finished") is None

    def test_function_response_produces_summary(self) -> None:
        ctx = MagicMock()
        ctx.state = {"velocity": 5.0, "water": 80, "distance": 10.0, "exhausted": False}
        req = _make_request(
            _user_content('{"event": "start_gun"}'),
            _function_response_content(),
        )
        response = autopilot_callback(ctx, req)
        _get_text(response)

    def test_tick_zero_initializes_runner_via_callback(self) -> None:
        """Tick 0 through the callback should inject _session_id and init runner."""
        ctx = MagicMock()
        ctx.state = {}
        ctx.session.id = "test-tick0-session"
        req = _make_request(
            _user_content('{"event": "tick", "data": {"tick": 0, "minutes_per_tick": 0, "elapsed_minutes": 0}}')
        )
        response = autopilot_callback(ctx, req)
        fc = _get_fc(response)
        assert fc.name == "process_tick"
        # Runner should be initialized with session-specific velocity
        assert ctx.state.get("velocity") is not None
        assert ctx.state["velocity"] > 0

    def test_tick_zero_uses_session_id_for_deterministic_seed(self) -> None:
        """Two runners with different session_ids should get different velocities."""
        ctx1 = MagicMock()
        ctx1.state = {}
        ctx1.session.id = "runner-aaa"
        ctx2 = MagicMock()
        ctx2.state = {}
        ctx2.session.id = "runner-bbb"
        tick_msg = '{"event": "tick", "data": {"tick": 0, "minutes_per_tick": 0}}'
        autopilot_callback(ctx1, _make_request(_user_content(tick_msg)))
        autopilot_callback(ctx2, _make_request(_user_content(tick_msg)))
        # Different session_ids should produce different velocities
        assert ctx1.state["velocity"] != ctx2.state["velocity"]

    def test_unknown_event_returns_text(self) -> None:
        ctx = MagicMock()
        ctx.state = {}
        req = _make_request(_user_content("random gibberish"))
        response = autopilot_callback(ctx, req)
        _get_text(response)
