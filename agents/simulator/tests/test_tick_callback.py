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

"""Tests for the deterministic tick_callback (before_model_callback)."""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from agents.simulator.tick_callback import _detect_phase, tick_callback


def _make_callback_context(state: dict | None = None) -> MagicMock:
    """Create a mock CallbackContext with a mutable state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


# ---------------------------------------------------------------------------
# _detect_phase
# ---------------------------------------------------------------------------
class TestDetectPhase:
    """Unit tests for _detect_phase."""

    def test_empty_contents_returns_advance(self):
        """No contents → ADVANCE phase."""
        req = LlmRequest(contents=[])
        assert _detect_phase(req) == "advance"

    def test_advance_tick_response_returns_check(self):
        """Last content has function_response.name == 'advance_tick' → CHECK."""
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[types.Part(function_response=types.FunctionResponse(name="advance_tick", response={}))],
                )
            ]
        )
        assert _detect_phase(req) == "check"

    def test_check_race_complete_response_returns_summarize(self):
        """Last content has function_response.name == 'check_race_complete' → SUMMARIZE."""
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[
                        types.Part(function_response=types.FunctionResponse(name="check_race_complete", response={}))
                    ],
                )
            ]
        )
        assert _detect_phase(req) == "summarize"

    def test_unknown_function_response_returns_advance(self):
        """Last content has unknown function_response name → ADVANCE."""
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[types.Part(function_response=types.FunctionResponse(name="some_other_tool", response={}))],
                )
            ]
        )
        assert _detect_phase(req) == "advance"

    def test_text_content_returns_advance(self):
        """Last content has text only (no function_response) → ADVANCE."""
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Hello world")],
                )
            ]
        )
        assert _detect_phase(req) == "advance"


# ---------------------------------------------------------------------------
# tick_callback
# ---------------------------------------------------------------------------
class TestTickCallback:
    """Unit tests for tick_callback."""

    def test_advance_phase_returns_advance_tick_call(self):
        """In ADVANCE phase, tick_callback returns FunctionCall for advance_tick."""
        ctx = _make_callback_context(state={"current_tick": 1, "max_ticks": 10})
        req = LlmRequest(contents=[])

        response = tick_callback(callback_context=ctx, llm_request=req)

        assert response.content is not None
        parts = response.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "advance_tick"

    def test_check_phase_returns_check_race_complete_call(self):
        """In CHECK phase, tick_callback returns FunctionCall for check_race_complete."""
        ctx = _make_callback_context(state={"current_tick": 1, "max_ticks": 10})
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[types.Part(function_response=types.FunctionResponse(name="advance_tick", response={}))],
                )
            ]
        )

        response = tick_callback(callback_context=ctx, llm_request=req)

        assert response.content is not None
        parts = response.content.parts
        assert parts is not None
        assert len(parts) == 1
        fc = parts[0].function_call
        assert fc is not None
        assert fc.name == "check_race_complete"

    def test_summarize_phase_returns_text(self):
        """In SUMMARIZE phase, tick_callback returns a text response."""
        ctx = _make_callback_context(state={"current_tick": 5, "max_ticks": 10})
        req = LlmRequest(
            contents=[
                types.Content(
                    role="model",
                    parts=[
                        types.Part(function_response=types.FunctionResponse(name="check_race_complete", response={}))
                    ],
                )
            ]
        )

        response = tick_callback(callback_context=ctx, llm_request=req)

        assert response.content is not None
        parts = response.content.parts
        assert parts is not None
        assert len(parts) == 1
        assert parts[0].text is not None
        assert "5/10" in parts[0].text
