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

# agents/utils/tests/test_dash_log_text_emission.py
"""Regression: the plugin's narrative emission carries `event=type_val`.

The chat is fed by the dispatcher's passthrough at
`agents/utils/dispatcher.py:624-666`, which emits `event=text`. The plugin's
own `_emit_narrative` emission carries the source `type_val` (`model_end`,
`model_error`, `tool_end`, ...), so the frontend silently drops the plugin
copy and renders only the dispatcher's clean version -- avoiding duplicate
chat messages. This contract was implicit before bbaf5c01 (the plugin
emitted `event=type_val` and the FE dropped it); bbaf5c01 changed the
plugin to emit `event=text` which exposed the duplication; the revert
restores the historical contract while keeping bbaf5c01's payload cleanup.

These tests pin two things:
  * Matrix (plugin x agent x payload_type): the plugin's narrative
    emission carries `event=<payload_type>` (NOT `event=text`).
  * Shape (function-call-only / mixed / empty): the gate in
    `_emit_narrative` skips empty and function-call-only turns; mixed
    turns emit a single narrative message containing the text part only
    (no protobuf garbage).

If chat duplicates re-appear, check whether someone re-changed `event` to
`"text"` in `_emit_narrative` and broke this contract.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agents.utils.plugins import BaseDashLogPlugin, DashLogPlugin, RedisDashLogPlugin


def _terminal_text_response(text: str) -> LlmResponse:
    """Build the LlmResponse the model returns on its last text-only turn."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=text)],
        ),
        turn_complete=True,
        partial=False,
    )


def _function_call_only_response(name: str, args: dict[str, Any]) -> LlmResponse:
    """Turn that only invokes a tool -- no narrative text Part."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
        ),
        turn_complete=True,
        partial=False,
    )


def _mixed_text_and_function_call_response(text: str, name: str, args: dict[str, Any]) -> LlmResponse:
    """Turn that emits narrative text AND invokes a tool in the same response."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text=text),
                types.Part(function_call=types.FunctionCall(name=name, args=args)),
            ],
        ),
        turn_complete=True,
        partial=False,
    )


def _empty_response() -> LlmResponse:
    """Terminal turn with no Parts at all."""
    return LlmResponse(
        content=types.Content(role="model", parts=[]),
        turn_complete=True,
        partial=False,
    )


def _callback_context(agent_name: str, session_id: str) -> SimpleNamespace:
    """Minimal CallbackContext stand-in matching the attrs `_publish` reads.

    `state` is intentionally empty -- this test only asserts the wire `event`
    field; `simulation_id` resolution is covered by
    `test_plugin_simulation_id.py`.
    """
    session = SimpleNamespace(id=session_id, state={})
    return SimpleNamespace(
        agent_name=agent_name,
        session=session,
        state=session.state,
        invocation_id="inv-1",
    )


PluginCls = type[DashLogPlugin] | type[RedisDashLogPlugin]


def _make_plugin(plugin_cls: PluginCls, agent_name: str) -> BaseDashLogPlugin:
    """Construct a DashLog plugin without touching live Pub/Sub.

    Wraps construction in `patch("agents.utils.plugins.pubsub_v1")` per the
    project pattern (see `test_plugin_simulation_id.py:36`) so
    `_init_transport` does not instantiate a real `PublisherClient`.
    """
    with patch("agents.utils.plugins.pubsub_v1"):
        plugin = plugin_cls(agent_display_names={agent_name: agent_name.title()})
    return plugin


async def _invoke(plugin: BaseDashLogPlugin, payload_type: str, ctx: Any, message: str) -> None:
    """Dispatch to the right callback for the payload type under test."""
    if payload_type == "model_end":
        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_terminal_text_response(message),
        )
    elif payload_type == "model_error":
        # `on_model_error_callback` does not read `llm_request`; passing
        # `None` keeps the harness focused on the narrative emission path.
        await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=None,  # type: ignore[arg-type]
            error=RuntimeError(message),
        )
    else:  # pragma: no cover - guard against typos in parametrize axis
        raise AssertionError(f"unknown payload_type: {payload_type!r}")


def _expected_substring(payload_type: str, message: str) -> str:
    """Snippet that must appear in the emitted text payload.

    `_emit_narrative` prefixes error payloads with `"Error: "` (see
    `agents/utils/plugins.py:411-416`); model_end payloads pass through as-is.
    """
    if payload_type == "model_error":
        return f"Error: {message}"
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_cls", [RedisDashLogPlugin, DashLogPlugin])
@pytest.mark.parametrize(
    "agent_name",
    [
        "planner",
        "planner_with_eval",
        "planner_with_memory",
        "simulator",
        "simulator_with_failure",
    ],
)
@pytest.mark.parametrize("payload_type", ["model_end", "model_error"])
async def test_plugin_narrative_emits_event_using_type_val(
    plugin_cls: PluginCls,
    agent_name: str,
    payload_type: str,
):
    """Every plugin x agent x narrative-source must emit `event=<payload_type>`.

    The wire `event` field carries the source `type_val` (e.g. `model_end`,
    `model_error`). The frontend silently drops these in favor of the
    dispatcher's `event=text` emission, avoiding the duplicate chat messages
    that bbaf5c01 (briefly) caused. Parametrized over both
    `BaseDashLogPlugin` subclasses so a future override of `_emit_narrative`
    on either class is caught, and over both narrative-bearing payload types
    since the contract covers errors too.
    """
    plugin = _make_plugin(plugin_cls, agent_name)
    ctx = _callback_context(agent_name=agent_name, session_id=f"sess-{agent_name}")
    message = f"Narrative from {agent_name}: planning complete."

    captured: list[dict[str, Any]] = []

    async def fake_emit(**kwargs):
        captured.append(kwargs)

    # NOTE: `_emit_narrative` does a local
    # `from agents.utils.pulses import emit_gateway_message` at call time
    # (see `agents/utils/plugins.py:386`), so the patch target is the source
    # module (`agents.utils.pulses`), not the `agents.utils.plugins`
    # namespace.
    with (
        patch.object(plugin, "_do_publish", new=AsyncMock(return_value=None)),
        patch(
            "agents.utils.pulses.emit_gateway_message",
            new=AsyncMock(side_effect=fake_emit),
        ),
    ):
        await _invoke(plugin, payload_type, ctx, message)

    narrative_events = [e for e in captured if e.get("event") == payload_type]
    assert len(narrative_events) == 1, (
        f"Expected exactly one event={payload_type} emission from "
        f"{plugin_cls.__name__}/{agent_name}/{payload_type}; "
        f"got events: {[e.get('event') for e in captured]}"
    )
    # Plugin must NOT emit event=text (the dispatcher's lane).
    text_events = [e for e in captured if e.get("event") == "text"]
    assert text_events == [], (
        f"Plugin must not emit event=text (dispatcher owns that lane); "
        f"got: {[e.get('data', {}).get('text') for e in text_events]}"
    )
    assert _expected_substring(payload_type, message) in narrative_events[0]["data"]["text"]


# --- Content-shape regressions -------------------------------------------
#
# These tests pin three properties of `_emit_narrative`:
#   1. The gate (`if clean_text and final_text:`) skips narrative emission
#      for empty / function-call-only turns -- no preamble-only chat bubble.
#   2. Mixed turns emit narrative containing only the actual text Part --
#      no protobuf garbage from `function_call=FunctionCall(...)` reprs.
#   3. The narrative emission carries `msg_type=text` (this filter is what
#      catches the gate's effect; the wire `event` is now `model_end` per
#      the matrix tests above, not `text`).
#
# Single parametrization (RedisDashLogPlugin x planner) is sufficient: the
# matrix above already proves the cross-axis behavior; these tests focus on
# response-shape handling inside `after_model_callback`.


@pytest.mark.asyncio
async def test_function_call_only_turn_emits_no_text():
    """A turn that only invokes a tool must not emit narrative text.

    Function calls are surfaced via the lifecycle path (`tool_start` /
    `tool_end`); the narrative path must stay silent for them. Prior to the
    fix the Pydantic repr of the `FunctionCall` Part leaked into chat text.
    """
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-fc")

    captured: list[dict[str, Any]] = []

    async def fake_emit(**kwargs):
        captured.append(kwargs)

    with (
        patch.object(plugin, "_do_publish", new=AsyncMock(return_value=None)),
        patch(
            "agents.utils.pulses.emit_gateway_message",
            new=AsyncMock(side_effect=fake_emit),
        ),
    ):
        await plugin.after_model_callback(
            callback_context=ctx,  # type: ignore[arg-type]  # SimpleNamespace stand-in
            llm_response=_function_call_only_response("load_skill", {"skill_name": "gis-spatial-engineering"}),
        )

    narrative_emissions = [e for e in captured if e.get("msg_type") == "text"]
    assert narrative_emissions == [], (
        f"Function-call-only turn must not emit narrative; got: "
        f"{[e.get('data', {}).get('text') for e in narrative_emissions]}"
    )


@pytest.mark.asyncio
async def test_mixed_text_and_function_call_emits_text_only():
    """Mixed turn must emit only the actual text -- no protobuf repr."""
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-mixed")

    captured: list[dict[str, Any]] = []

    async def fake_emit(**kwargs):
        captured.append(kwargs)

    with (
        patch.object(plugin, "_do_publish", new=AsyncMock(return_value=None)),
        patch(
            "agents.utils.pulses.emit_gateway_message",
            new=AsyncMock(side_effect=fake_emit),
        ),
    ):
        await plugin.after_model_callback(
            callback_context=ctx,  # type: ignore[arg-type]  # SimpleNamespace stand-in
            llm_response=_mixed_text_and_function_call_response(
                "Here is the plan.",
                "load_skill",
                {"skill_name": "gis-spatial-engineering"},
            ),
        )

    narrative_emissions = [e for e in captured if e.get("msg_type") == "text"]
    assert len(narrative_emissions) == 1, (
        f"Mixed turn must emit exactly one narrative message; got: {[e.get('event') for e in captured]}"
    )
    # Plugin's narrative carries the source type as wire event (NOT `text`).
    assert narrative_emissions[0]["event"] == "model_end"
    body = narrative_emissions[0]["data"]["text"]
    assert "Here is the plan." in body, body
    # No protobuf garbage from the function_call Part.
    assert "function_call" not in body, body
    assert "FunctionCall" not in body, body
    assert "thought_signature" not in body, body


@pytest.mark.asyncio
async def test_empty_turn_emits_no_text():
    """A turn with no Parts must not emit any narrative event."""
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-empty")

    captured: list[dict[str, Any]] = []

    async def fake_emit(**kwargs):
        captured.append(kwargs)

    with (
        patch.object(plugin, "_do_publish", new=AsyncMock(return_value=None)),
        patch(
            "agents.utils.pulses.emit_gateway_message",
            new=AsyncMock(side_effect=fake_emit),
        ),
    ):
        await plugin.after_model_callback(
            callback_context=ctx,  # type: ignore[arg-type]  # SimpleNamespace stand-in
            llm_response=_empty_response(),
        )

    narrative_emissions = [e for e in captured if e.get("msg_type") == "text"]
    assert narrative_emissions == [], (
        f"Empty turn must not emit narrative; got: {[e.get('data', {}).get('text') for e in narrative_emissions]}"
    )


# --- Published-payload shape regressions ---------------------------------
#
# The chat path (event=text) and the dashboard renderer
# (web/agent-dash/index.html:864) are different consumers of the model_end
# payload. Sharing a single `response.content` field forced a tradeoff:
# either the dashboard saw protobuf garbage (pre-bbaf5c01) or it saw an
# empty turn for every function-call-only model_end (post-bbaf5c01).
#
# The payload now carries three distinct fields:
#   - response.text          : verbatim text-only, source for chat narrative
#   - response.function_calls: structured list for tooling
#   - response.content       : human-readable summary for the dashboard
#
# These tests lock that contract by capturing the payload handed to
# `_do_publish` (which is what the dashboard subscribes to via the Redis /
# Pub/Sub transport).


async def _capture_published_payload(
    plugin: BaseDashLogPlugin, callback_context: Any, llm_response: LlmResponse
) -> dict[str, Any]:
    """Run after_model_callback and return the dict passed to _do_publish."""
    mock_do_publish = AsyncMock(return_value=None)
    with (
        patch.object(plugin, "_do_publish", new=mock_do_publish),
        patch(
            "agents.utils.pulses.emit_gateway_message",
            new=AsyncMock(return_value=None),
        ),
    ):
        await plugin.after_model_callback(
            callback_context=callback_context,
            llm_response=llm_response,
        )
    mock_do_publish.assert_called_once()
    _ctx, payload = mock_do_publish.call_args.args
    return payload


@pytest.mark.asyncio
async def test_published_payload_text_only_response():
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-pt")

    payload = await _capture_published_payload(
        plugin,
        ctx,  # type: ignore[arg-type]  # SimpleNamespace stand-in
        _terminal_text_response("Marathon planned across the Vegas Strip."),
    )

    assert payload["type"] == "model_end"
    response = payload["response"]
    assert response["text"] == "Marathon planned across the Vegas Strip."
    # `content` mirrors `text` when there are no function calls.
    assert response["content"] == "Marathon planned across the Vegas Strip."
    assert response["function_calls"] == []


@pytest.mark.asyncio
async def test_published_payload_function_call_only_response():
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-pf")

    payload = await _capture_published_payload(
        plugin,
        ctx,  # type: ignore[arg-type]
        _function_call_only_response("load_skill", {"skill_name": "gis-spatial-engineering"}),
    )

    response = payload["response"]
    # `text` is empty -- no narrative for the chat.
    assert response["text"] == ""
    # Dashboard-facing summary: arrow line per call.
    assert response["content"] == "→ load_skill(skill_name='gis-spatial-engineering')"
    # Structured form for tooling.
    assert response["function_calls"] == [
        {"name": "load_skill", "args": {"skill_name": "gis-spatial-engineering"}},
    ]
    # No protobuf garbage anywhere in the dashboard summary.
    for forbidden in ("function_call=", "FunctionCall(", "thought_signature"):
        assert forbidden not in response["content"], response["content"]


@pytest.mark.asyncio
async def test_published_payload_mixed_response():
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-pm")

    payload = await _capture_published_payload(
        plugin,
        ctx,  # type: ignore[arg-type]
        _mixed_text_and_function_call_response(
            "Here is the plan.",
            "load_skill",
            {"skill_name": "gis-spatial-engineering"},
        ),
    )

    response = payload["response"]
    # `text` carries only the verbatim text Part.
    assert response["text"] == "Here is the plan."
    # `content` joins text and the function-call line with a blank-line separator.
    assert response["content"] == "Here is the plan.\n\n→ load_skill(skill_name='gis-spatial-engineering')"
    assert response["function_calls"] == [
        {"name": "load_skill", "args": {"skill_name": "gis-spatial-engineering"}},
    ]
    for forbidden in ("function_call=", "FunctionCall(", "thought_signature"):
        assert forbidden not in response["content"], response["content"]


@pytest.mark.asyncio
async def test_published_payload_empty_response():
    plugin = _make_plugin(RedisDashLogPlugin, "planner")
    ctx = _callback_context(agent_name="planner", session_id="sess-pe")

    payload = await _capture_published_payload(
        plugin,
        ctx,  # type: ignore[arg-type]
        _empty_response(),
    )

    response = payload["response"]
    assert response["text"] == ""
    assert response["content"] == ""
    assert response["function_calls"] == []


def test_build_response_summary_function_call_args_fallback():
    """Defensive: when `dict(fc.args)` raises, args fall back to {`_repr`: ...}.

    Real-world trigger: protobuf MapComposite values that look dict-like but
    refuse `dict()` conversion. The helper must never propagate the
    exception. Tested directly against the helper because pydantic v2
    strictly validates `FunctionCall.args` at construction time and would
    reject a non-dict before we could exercise the runtime fallback.
    """
    from agents.utils.plugins import _build_response_summary

    class _UnDictable:
        """Stand-in for an args object that breaks `dict(...)`."""

        def __iter__(self):
            raise TypeError("not iterable")

        def keys(self):
            raise TypeError("no keys")

        def __repr__(self) -> str:
            return "<UnDictable>"

    fc = SimpleNamespace(name="load_skill", args=_UnDictable())
    parts = [SimpleNamespace(text=None, function_call=fc)]

    text, content, function_calls = _build_response_summary(parts)

    assert text == ""
    assert function_calls == [{"name": "load_skill", "args": {"_repr": "<UnDictable>"}}]
    assert content == "→ load_skill(_repr='<UnDictable>')"
