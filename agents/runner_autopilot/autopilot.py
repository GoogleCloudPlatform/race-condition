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

"""Deterministic callback logic for the runner_autopilot agent.

Implements a before_model_callback that always returns an LlmResponse,
preventing any LLM model calls. The callback uses a message dispatcher
pattern: classify the incoming message, dispatch to a handler, return
tool calls or text.

This module is pure logic — no ADK agent construction. All functions are
independently testable with mock state dicts and LlmRequest objects.
"""

import logging
import random
from collections.abc import Callable
from enum import Enum
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agents.runner.initialization import initialize_runner
from agents.utils.runner_protocol import RunnerEventType, parse_runner_event

logger = logging.getLogger(__name__)

# State can be a plain dict (unit tests) or ADK State object (runtime).
# Both support .get(key, default). We use Any to avoid Pyright conflicts
# between dict.get() overloads and custom protocol signatures.
StateLike = Any


class Phase(str, Enum):
    """Which phase of the callback loop we're in."""

    DECIDE = "decide"
    SUMMARIZE = "summarize"


def detect_phase(llm_request: LlmRequest) -> Phase:
    """Determine whether we're deciding tool calls or summarizing results.

    After ADK executes tool calls, it appends function_response parts and
    calls before_model_callback again. We detect this by checking the last
    content entry for function_response parts.
    """
    if not llm_request.contents:
        return Phase.DECIDE

    last = llm_request.contents[-1]
    if last.parts:
        for part in last.parts:
            if part.function_response is not None:
                return Phase.SUMMARIZE

    return Phase.DECIDE


def extract_last_user_text(llm_request: LlmRequest) -> str:
    """Extract the text from the last user message in the request.

    Walks backwards through contents to find the last content with role='user'
    that has text parts, skipping model responses and function_response entries.
    """
    for content in reversed(llm_request.contents):
        if content.role != "user":
            continue
        if content.parts:
            for part in content.parts:
                if part.text is not None:
                    return part.text
    return ""


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


# [START autopilot_responses]
def _function_call_response(name: str, args: dict) -> LlmResponse:
    """Build an LlmResponse containing a single FunctionCall."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
        ),
    )


def _text_response(text: str) -> LlmResponse:
    """Build an LlmResponse containing a text part."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )


# [END autopilot_responses]


# ---------------------------------------------------------------------------
# Event handlers — pure functions: (state, data) -> LlmResponse
# ---------------------------------------------------------------------------


def handle_start_gun(state: StateLike, data: dict) -> LlmResponse:
    """Race started. Acknowledge the start gun.

    Runner initialization is deferred to tick 0 (via handle_tick) so that
    the first tick reports initial velocity at distance=0 without advancing.
    """
    return _text_response("Start gun heard. Awaiting first tick.")


def handle_crowd_boost(state: StateLike, data: dict) -> LlmResponse:
    """Crowd cheering. Accelerate with provided or default intensity."""
    intensity = data.get("intensity", 0.5)
    return _function_call_response("accelerate", {"intensity": float(intensity)})


def handle_distance_update(state: StateLike, data: dict) -> LlmResponse:
    """No-op for autopilot runners -- process_tick handles all depletion.

    The frontend sends distance_update events on mile boundary crossings,
    but process_tick already depletes water with its own calibrated physics
    (BASE_DEPLETION_RATE * miles * efficiency * fatigue_growth) and handles
    auto-hydration at stations.  Calling deplete_water here would cause
    double depletion (~4x intended rate), leading to universal collapse.

    The LLM-powered runner agent still has deplete_water as a tool and can
    use it via its own decision-making, but the autopilot must not.
    """
    return _text_response("Distance update acknowledged (depletion handled by process_tick).")


def handle_hydration_station(state: StateLike, data: dict) -> LlmResponse:
    """Hydration station triggered externally. Decide whether to stop.

    This handler is for manually triggered HYDRATION_STATION events (e.g.,
    from the frontend). During tick-driven races, hydration is handled
    internally by process_tick's auto-hydration logic, which uses a seeded
    RNG for determinism. This handler uses the global RNG and is therefore
    non-deterministic across runs.

    Rules:
    - <=40: always rehydrate (+30)
    - 41-60: 50% chance to stop
    - >60: 30% chance to stop
    - Exhausted: always stop
    """
    water = state.get("water", 100)
    exhausted = state.get("exhausted", False)

    should_stop = (
        exhausted or water <= 40 or (water <= 60 and random.random() < 0.5) or (water > 60 and random.random() < 0.3)
    )

    if should_stop:
        return _function_call_response("rehydrate", {"amount": 30.0})

    return _text_response("Skipping hydration station, feeling strong.")


def handle_tick(state: StateLike, data: dict) -> LlmResponse:
    """Per-tick update. Initializes runner on first tick, then process_tick.

    On tick 0 (minutes_per_tick=0), initializes the runner profile from a
    seeded log-normal distribution and reports initial velocity at distance=0.
    On subsequent ticks, advances distance normally.

    Finished and collapsed runners still call process_tick to emit a
    tool_end event with their preserved state.  The process_tick function
    handles these cases as no-ops (mi_this_tick=0, effective_velocity=0)
    while keeping velocity/distance/water in the telemetry payload.
    Without this, advance_tick aggregation cannot see the runner and
    runners_reporting drops to zero once all runners finish.
    """
    # Initialize on first tick if not yet done.
    if state.get("velocity") is None:
        session_id = data.get("_session_id", "default")
        runner_count = data.get("runner_count", 1)
        initialize_runner(state, session_id, runner_count=runner_count)

    args: dict = {
        "minutes_per_tick": data.get("minutes_per_tick", 15.0),
        "elapsed_minutes": data.get("elapsed_minutes", 0.0),
        "race_distance_mi": data.get("race_distance_mi", 26.2188),
        "tick": data.get("tick", 0),
        # process_tick now requires inner_thought (Task I made it
        # schema-required to prevent small-model LLM runners from dropping
        # the optional field). The deterministic autopilot has no LLM to
        # generate prose; empty string preserves the prior result shape.
        "inner_thought": "",
    }
    collector_key = data.get("collector_buffer_key", "")
    if collector_key:
        args["collector_buffer_key"] = collector_key
    return _function_call_response("process_tick", args)


def build_summary(state: StateLike) -> LlmResponse:
    """Build a one-sentence summary after tool execution."""
    velocity = state.get("velocity", 0.0)
    water = state.get("water", 100)
    distance = state.get("distance", 0.0)
    exhausted = state.get("exhausted", False)
    finished = state.get("finished", False)
    collapsed = state.get("collapsed", False)
    if finished:
        status = "finished"
    elif collapsed:
        status = "collapsed"
    elif exhausted:
        status = "exhausted"
    else:
        status = "running"
    return _text_response(f"Status: {status}, velocity={velocity:.1f}, water={water:.0f}%, distance={distance:.1f}mi")


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

# [START autopilot_dispatch]
HANDLERS: dict[RunnerEventType, Callable[[StateLike, dict], LlmResponse]] = {
    RunnerEventType.START_GUN: handle_start_gun,
    RunnerEventType.CROWD_BOOST: handle_crowd_boost,
    RunnerEventType.DISTANCE_UPDATE: handle_distance_update,
    RunnerEventType.HYDRATION_STATION: handle_hydration_station,
    RunnerEventType.TICK: handle_tick,
}


# ---------------------------------------------------------------------------
# The callback — wired to LlmAgent.before_model_callback
# ---------------------------------------------------------------------------


def autopilot_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse:
    """Deterministic before_model_callback that always intercepts.

    Called by ADK's BaseLlmFlow in a loop:
    1. First call: parse user message, return tool calls or text
    2. After tools execute: called again with function_response in contents,
       return summary text

    Returns LlmResponse always — the model is never invoked.
    """
    phase = detect_phase(llm_request)
    state = callback_context.state

    if phase == Phase.SUMMARIZE:
        return build_summary(state)

    text = extract_last_user_text(llm_request)
    event = parse_runner_event(text)

    handler = HANDLERS.get(event.event)
    if handler is None:
        logger.debug("Unknown event type %s, returning no-op text", event.event)
        return _text_response(f"Received unknown event: {text[:100]}")

    # Inject session_id for handlers that need it (START_GUN for ack,
    # TICK for initialize_runner on tick 0).
    if event.event in (RunnerEventType.START_GUN, RunnerEventType.TICK):
        event.data["_session_id"] = getattr(getattr(callback_context, "session", None), "id", "default")

    return handler(state, event.data)


# [END autopilot_dispatch]
