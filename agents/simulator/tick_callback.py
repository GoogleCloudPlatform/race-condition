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

"""Deterministic callback for the tick agent.

Implements a before_model_callback that always returns an LlmResponse,
preventing any LLM model calls.  The tick agent's job is mechanical:
call advance_tick, then check_race_complete, every iteration.  Using a
callback instead of the LLM makes this 100% reliable and zero-cost.

The actual tool functions still execute (producing tool_end events that
flow to the gateway/frontend), but the *decision* to call them is
deterministic.

Three-phase state machine per LoopAgent iteration:
1. ADVANCE   — return FunctionCall for advance_tick
2. CHECK     — return FunctionCall for check_race_complete
3. SUMMARIZE — return text summary (ends the iteration)
"""

import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)


def _function_call(name: str) -> LlmResponse:
    """Build an LlmResponse containing a single FunctionCall with no args."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))],
        ),
    )


def _text(msg: str) -> LlmResponse:
    """Build an LlmResponse containing a text part."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=msg)],
        ),
    )


def _detect_phase(llm_request: LlmRequest) -> str:
    """Detect the current phase by inspecting the LAST content entry only.

    ADK appends function_response parts after each tool execution, then
    calls before_model_callback again.  We check the last content entry:

    - No contents or last has no function_response → ADVANCE
    - Last has function_response for advance_tick → CHECK
    - Last has function_response for check_race_complete → SUMMARIZE
    """
    if not llm_request.contents:
        return "advance"

    last = llm_request.contents[-1]
    for part in reversed(last.parts or []):
        if part.function_response is not None:
            name = part.function_response.name
            if name == "advance_tick":
                return "check"
            if name == "check_race_complete":
                return "summarize"

    return "advance"


def tick_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse:
    """Deterministic before_model_callback for the tick agent.

    Called by ADK's BaseLlmFlow in a loop:
    1. First call (no function_response in last content): call advance_tick
    2. After advance_tick (last response is advance_tick): call check_race_complete
    3. After check_race_complete (last response is check_race_complete): return text

    The actual tools execute normally, producing tool_end events for the
    gateway.  Only the *decision* is deterministic.
    """
    phase = _detect_phase(llm_request)

    if phase == "advance":
        tick = callback_context.state.get("current_tick", 0)
        max_ticks = callback_context.state.get("max_ticks", 0)
        logger.debug("tick_callback: ADVANCE phase, tick %d/%d", tick, max_ticks)
        return _function_call("advance_tick")

    if phase == "check":
        logger.debug("tick_callback: CHECK phase")
        return _function_call("check_race_complete")

    # SUMMARIZE: both tools done, end this LoopAgent iteration
    tick = callback_context.state.get("current_tick", 0)
    max_ticks = callback_context.state.get("max_ticks", 0)
    logger.debug("tick_callback: SUMMARIZE phase, tick %d/%d", tick, max_ticks)
    return _text(f"Tick {tick}/{max_ticks} complete.")
