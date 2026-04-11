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

"""Deterministic callback for the pre-race agent.

Implements a before_model_callback that always returns an LlmResponse,
preventing any LLM model calls.  The pre-race agent's job is mechanical:
call prepare_simulation, spawn_runners, start_race_collector, then
fire_start_gun in strict sequence.  Using a callback instead of the LLM
makes this 100% reliable and zero-cost.

The actual tool functions still execute (producing tool_end events that
flow to the gateway/frontend), but the *decision* to call them is
deterministic.

Five-phase state machine:
1. PREPARE  — call prepare_simulation with the incoming plan JSON
2. SPAWN    — call spawn_runners with count from state
3. COLLECT  — call start_race_collector
4. START    — call fire_start_gun
5. DONE     — return text summary (ends the agent)
"""

import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

# Ordered sequence of tool calls.  Phase detection works by finding the
# last function_response name and advancing to the next tool in this list.
_TOOL_SEQUENCE = [
    "prepare_simulation",
    "spawn_runners",
    "start_race_collector",
    "fire_start_gun",
]


def _function_call(name: str, args: dict | None = None) -> LlmResponse:
    """Build an LlmResponse containing a single FunctionCall."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(name=name, args=args or {}),
                )
            ],
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


def _extract_plan_json(llm_request: LlmRequest) -> str:
    """Extract the plan JSON string from the first user message."""
    for content in llm_request.contents:
        if content.role == "user":
            for part in content.parts or []:
                if part.text:
                    return part.text
    return "{}"


def _detect_phase(llm_request: LlmRequest) -> str:
    """Detect the current phase from the last function_response in contents.

    Scans backward through the last content entry's parts looking for a
    function_response.  The response name tells us which tool just
    completed, and we advance to the next tool in the sequence.

    Returns one of: "prepare", "spawn", "collect", "start", "done".
    """
    if not llm_request.contents:
        return "prepare"

    last = llm_request.contents[-1]
    for part in reversed(last.parts or []):
        if part.function_response is not None:
            name = part.function_response.name
            if name == "prepare_simulation":
                return "spawn"
            if name == "spawn_runners":
                return "collect"
            if name == "start_race_collector":
                return "start"
            if name == "fire_start_gun":
                return "done"

    return "prepare"


def pre_race_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse:
    """Deterministic before_model_callback for the pre-race agent.

    Called by ADK's BaseLlmFlow in a loop:
    1. First call (no function_response): call prepare_simulation
    2. After prepare_simulation: call spawn_runners
    3. After spawn_runners: call start_race_collector
    4. After start_race_collector: call fire_start_gun
    5. After fire_start_gun: return text (ends the agent)

    The actual tools execute normally, producing tool_end events for the
    gateway.  Only the *decision* is deterministic.
    """
    phase = _detect_phase(llm_request)

    if phase == "prepare":
        plan_json = _extract_plan_json(llm_request)
        logger.debug("pre_race_callback: PREPARE phase")
        return _function_call("prepare_simulation", {"plan_json": plan_json})

    if phase == "spawn":
        count = callback_context.state.get("runner_count", 10)
        logger.debug("pre_race_callback: SPAWN phase, count=%d", count)
        return _function_call("spawn_runners", {"count": count})

    if phase == "collect":
        logger.debug("pre_race_callback: COLLECT phase")
        return _function_call("start_race_collector")

    if phase == "start":
        logger.debug("pre_race_callback: START phase")
        return _function_call("fire_start_gun")

    # DONE: all tools complete, end the agent
    runner_count = callback_context.state.get("runner_count", 0)
    simulation_id = callback_context.state.get("simulation_id", "unknown")
    logger.debug(
        "pre_race_callback: DONE phase, %d runners, sim %s",
        runner_count,
        simulation_id,
    )
    return _text(f"Pre-race setup complete. {runner_count} runners ready for simulation {simulation_id}.")
