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

"""Tests for the deterministic pre-race callback.

Mirrors the approach in test_tick_callback.py: verify the five-phase
state machine produces the correct tool calls in sequence.
"""

from unittest.mock import MagicMock

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from agents.simulator.pre_race_callback import pre_race_callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(contents: list[types.Content] | None = None) -> LlmRequest:
    """Build a minimal LlmRequest with given contents."""
    req = MagicMock(spec=LlmRequest)
    req.contents = contents or []
    return req


def _make_ctx(state: dict | None = None) -> CallbackContext:
    """Build a CallbackContext mock with the given state dict."""
    ctx = MagicMock(spec=CallbackContext)
    ctx.state = state or {}
    return ctx


def _user_msg(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


def _fn_call(name: str, args: dict | None = None) -> types.Content:
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args or {}))],
    )


def _fn_response(name: str, response: dict | None = None) -> types.Content:
    return types.Content(
        role="tool",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    name=name,
                    response=response or {"status": "success"},
                )
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 1: PREPARE — no function_response yet → call prepare_simulation
# ---------------------------------------------------------------------------


class TestPreparePhase:
    def test_first_call_returns_prepare_simulation(self):
        """With only a user message, callback should call prepare_simulation."""
        plan = '{"action": "execute", "narrative": "test"}'
        req = _make_request([_user_msg(plan)])
        ctx = _make_ctx()

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "prepare_simulation"
        assert fc.args is not None
        assert fc.args["plan_json"] == plan

    def test_empty_contents_returns_prepare_simulation(self):
        """With no contents at all, callback still calls prepare_simulation."""
        req = _make_request([])
        ctx = _make_ctx()

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "prepare_simulation"
        assert fc.args is not None
        assert fc.args["plan_json"] == "{}"


# ---------------------------------------------------------------------------
# Phase 2: SPAWN — after prepare_simulation → call spawn_runners
# ---------------------------------------------------------------------------


class TestSpawnPhase:
    def test_after_prepare_returns_spawn_runners(self):
        """After prepare_simulation returns, callback should call spawn_runners."""
        req = _make_request(
            [
                _user_msg("plan"),
                _fn_call("prepare_simulation"),
                _fn_response("prepare_simulation"),
            ]
        )
        ctx = _make_ctx({"runner_count": 50})

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "spawn_runners"
        assert fc.args is not None
        assert fc.args["count"] == 50

    def test_spawn_uses_default_count(self):
        """If runner_count is not in state, default to 10."""
        req = _make_request(
            [
                _user_msg("plan"),
                _fn_call("prepare_simulation"),
                _fn_response("prepare_simulation"),
            ]
        )
        ctx = _make_ctx({})

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        fc = parts[0].function_call
        assert fc is not None
        assert fc.args is not None
        assert fc.args["count"] == 10


# ---------------------------------------------------------------------------
# Phase 3: COLLECT — after spawn_runners → call start_race_collector
# ---------------------------------------------------------------------------


class TestCollectPhase:
    def test_after_spawn_returns_start_race_collector(self):
        """After spawn_runners returns, callback should call start_race_collector."""
        req = _make_request(
            [
                _user_msg("plan"),
                _fn_call("prepare_simulation"),
                _fn_response("prepare_simulation"),
                _fn_call("spawn_runners"),
                _fn_response("spawn_runners"),
            ]
        )
        ctx = _make_ctx()

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "start_race_collector"


# ---------------------------------------------------------------------------
# Phase 4: START — after start_race_collector → call fire_start_gun
# ---------------------------------------------------------------------------


class TestStartPhase:
    def test_after_collect_returns_fire_start_gun(self):
        """After start_race_collector returns, callback should call fire_start_gun."""
        req = _make_request(
            [
                _user_msg("plan"),
                _fn_call("prepare_simulation"),
                _fn_response("prepare_simulation"),
                _fn_call("spawn_runners"),
                _fn_response("spawn_runners"),
                _fn_call("start_race_collector"),
                _fn_response("start_race_collector"),
            ]
        )
        ctx = _make_ctx()

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "fire_start_gun"


# ---------------------------------------------------------------------------
# Phase 5: DONE — after fire_start_gun → return text summary
# ---------------------------------------------------------------------------


class TestDonePhase:
    def test_after_start_gun_returns_text(self):
        """After fire_start_gun returns, callback should return text summary."""
        req = _make_request(
            [
                _user_msg("plan"),
                _fn_call("prepare_simulation"),
                _fn_response("prepare_simulation"),
                _fn_call("spawn_runners"),
                _fn_response("spawn_runners"),
                _fn_call("start_race_collector"),
                _fn_response("start_race_collector"),
                _fn_call("fire_start_gun"),
                _fn_response("fire_start_gun"),
            ]
        )
        ctx = _make_ctx({"runner_count": 10, "simulation_id": "sim-123"})

        result = pre_race_callback(ctx, req)

        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert len(parts) == 1
        assert parts[0].text is not None
        assert "sim-123" in parts[0].text
