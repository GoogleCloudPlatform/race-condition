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

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from collections import defaultdict

from dotenv import load_dotenv
from google.cloud import pubsub_v1

from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.agents.base_agent import BaseAgent
from google.genai import types

logger = logging.getLogger(__name__)

# Allowlist of tool args safe to include in tool_start lifecycle events.
# Maps tool_name -> list of arg keys to cherry-pick for display.
_TOOL_DISPLAY_HINTS: Dict[str, List[str]] = {
    "load_skill": ["skill_name"],
    "run_skill_script": ["skill_name", "script_path"],
    "call_agent": ["agent_name"],
}


def _safe_json_sanitize(obj: Any) -> Any:
    """Recursively convert non-serializable components of an object to strings."""
    # 0. Handle Pydantic / ADK Models efficiently
    if hasattr(obj, "dict") and callable(obj.dict):
        return _safe_json_sanitize(obj.dict())
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return _safe_json_sanitize(obj.model_dump())

    if isinstance(obj, dict):
        return {str(k): _safe_json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json_sanitize(i) for i in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _safe_json_dumps(obj: Any, **kwargs) -> str:
    """Safely dump objects to JSON, sanitizing non-serializable types first."""
    return json.dumps(_safe_json_sanitize(obj), **kwargs)


def _build_response_summary(parts: Any) -> tuple[str, str, list[dict[str, Any]]]:
    """Render an LlmResponse's parts into (text, content, function_calls).

    The model_end payload feeds two distinct consumers:
      * the chat narrative (`_emit_narrative` -> `event=text`), which needs
        verbatim text only, and
      * the dashboard (`web/agent-dash/index.html:864`), which needs a
        human-readable summary of EVERY model turn including those that
        emit only function calls.

    Returns:
      text: verbatim concatenation of `p.text` parts (empty when none).
        Source field for the chat path; gating on it skips empty turns.
      content: human-readable summary for the dashboard. Equals `text` when
        only text is present; lines like ``-> name(arg='value')`` joined
        with newlines when only function calls; text + blank line +
        function-call lines for mixed turns.
      function_calls: structured ``[{"name": str, "args": dict}, ...]`` for
        downstream tooling. ``args`` falls back to ``{"_repr": str(...)}``
        if ``dict(fc.args)`` raises (defensive against protobuf
        MapComposite or similar non-mapping inputs).
    """
    text_chunks: list[str] = []
    function_calls: list[dict[str, Any]] = []
    fc_lines: list[str] = []
    for p in parts or []:
        text_val = getattr(p, "text", None)
        if text_val:
            text_chunks.append(text_val)
        fc = getattr(p, "function_call", None)
        if fc is None or not getattr(fc, "name", None):
            continue
        try:
            args: dict[str, Any] = dict(fc.args or {})
        except Exception:
            args = {"_repr": str(fc.args)}
        function_calls.append({"name": fc.name, "args": args})
        rendered_args = ", ".join(f"{k}={v!r}" for k, v in args.items())
        fc_lines.append(f"\u2192 {fc.name}({rendered_args})")

    text = "".join(text_chunks)
    if text and fc_lines:
        content = text + "\n\n" + "\n".join(fc_lines)
    elif text:
        content = text
    elif fc_lines:
        content = "\n".join(fc_lines)
    else:
        content = ""
    return text, content, function_calls


class BaseDashLogPlugin(BasePlugin):
    """Base class for dashboard telemetry plugins.

    Subclasses must implement:
      - _init_transport(): Initialize transport-specific resources.
      - _do_publish(context, payload): Publish a payload via the transport.
    """

    def __init__(
        self,
        name: str,
        agent_display_names: dict[str, str] | None = None,
        fire_and_forget: bool = False,
        suppressed_events: set[str] | None = None,
    ):
        super().__init__(name=name)
        self._display_names: dict[str, str] = agent_display_names or {}
        self._fire_and_forget = fire_and_forget
        self._suppressed_events: set[str] = suppressed_events or set()
        self._sequence_counters = defaultdict(int)
        self._init_transport()

    def _init_transport(self) -> None:
        """Initialize transport-specific resources. Override in subclasses."""
        pass

    async def _do_publish(self, context: Any, payload: Dict[str, Any]) -> None:
        """Publish a payload via the transport. Must be overridden."""
        raise NotImplementedError

    # --- Shared Callback Implementations ---

    async def before_run_callback(self, *, invocation_context: InvocationContext) -> None:
        await self._publish(
            invocation_context,
            {
                "type": "run_start",
                "agent": invocation_context.agent.name,
                "user_id": invocation_context.user_id,
                "timestamp": time.time(),
            },
        )

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        await self._publish(
            invocation_context,
            {
                "type": "run_end",
                "agent": invocation_context.agent.name,
                "user_id": invocation_context.user_id,
                "timestamp": time.time(),
            },
        )

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        await self._publish(
            callback_context,
            {"type": "agent_start", "agent": agent.name, "timestamp": time.time()},
        )
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        await self._publish(
            callback_context,
            {"type": "agent_end", "agent": agent.name, "timestamp": time.time()},
        )
        return None

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: Dict[str, Any], tool_context: ToolContext
    ) -> Optional[Dict]:
        await self._publish(
            tool_context,
            {
                "type": "tool_start",
                "agent": tool_context.agent_name,
                "tool": tool.name,
                "args": tool_args,
                "timestamp": time.time(),
            },
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: Dict[str, Any],
        tool_context: ToolContext,
        result: Dict,
    ) -> Optional[Dict]:
        await self._publish(
            tool_context,
            {
                "type": "tool_end",
                "agent": tool_context.agent_name,
                "tool": tool.name,
                "result": result,
                "timestamp": time.time(),
            },
        )
        return None

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
        await self._publish(
            callback_context,
            {
                "type": "model_start",
                "agent": callback_context.agent_name,
                "model": llm_request.model,
                "timestamp": time.time(),
            },
        )
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        if llm_response.turn_complete is False or llm_response.partial is True:
            return None

        # Split the response into three fields with distinct consumers:
        #   * `text`           -> chat narrative (`_emit_narrative` reads
        #     this; gating on it skips empty turns and avoids the protobuf
        #     leak from older `p.text or str(p)` formulations).
        #   * `function_calls` -> structured list for tooling.
        #   * `content`        -> human-readable summary for the dashboard
        #     (`web/agent-dash/index.html:864`); shows arrow-prefixed lines
        #     for function-call-only turns instead of "(Turn Complete)".
        parts = llm_response.content.parts if llm_response.content and llm_response.content.parts else []
        resp_text, resp_content, resp_function_calls = _build_response_summary(parts)

        # Clean usage metadata
        usage = None
        if llm_response.usage_metadata:
            usage = {
                "prompt_token_count": llm_response.usage_metadata.prompt_token_count,
                "candidates_token_count": llm_response.usage_metadata.candidates_token_count,
                "total_token_count": llm_response.usage_metadata.total_token_count,
            }

        await self._publish(
            callback_context,
            {
                "type": "model_end",
                "agent": callback_context.agent_name,
                "response": {
                    "content": resp_content,
                    "text": resp_text,
                    "function_calls": resp_function_calls,
                    "usage": usage,
                },
                "timestamp": time.time(),
            },
        )
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        await self._publish(
            callback_context,
            {
                "type": "model_error",
                "agent": callback_context.agent_name,
                "error": str(error),
                "timestamp": time.time(),
            },
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: Dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[Dict]:
        await self._publish(
            tool_context,
            {
                "type": "tool_error",
                "agent": tool_context.agent_name,
                "tool": tool.name,
                "error": str(error),
                "timestamp": time.time(),
            },
        )
        return None

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        text = ""
        if user_message.parts:
            text = "".join([p.text or "" for p in user_message.parts])
        await self._publish(
            invocation_context,
            {
                "type": "user_message",
                "agent": invocation_context.agent.name,
                "content": text,
                "timestamp": time.time(),
            },
        )
        return None

    # --- Shared _publish Pipeline ---

    async def _publish(self, context: Any, payload: Dict[str, Any]) -> None:
        """Inject metadata, sequence, and delegate to transport + narrative."""
        session_id = getattr(context, "session", None)
        if session_id is not None and hasattr(session_id, "id"):
            session_id = session_id.id
        elif not session_id:
            session_id = "unknown-session"

        # On Agent Engine, VertexAiSessionService generates internal session
        # IDs that differ from the gateway's spawn session UUIDs.  Map back
        # to the original context_id so the frontend's session-based
        # rendering filters match the spawned agent.
        if session_id and session_id != "unknown-session":
            from agents.utils.simulation_registry import get_context_id

            original_id = await get_context_id(str(session_id))
            if original_id:
                session_id = original_id

        payload["session_id"] = str(session_id) if session_id else "unknown-session"

        inv_id = getattr(context, "invocation_id", None)
        payload["invocation_id"] = str(inv_id) if inv_id is not None else None

        payload["seq"] = self._sequence_counters[session_id]
        self._sequence_counters[session_id] += 1

        # Sanitize payload for any downstream JSON operations
        safe_payload = json.loads(_safe_json_dumps(payload))

        # Skip suppressed events entirely (e.g. run_start, model_start for runners)
        if safe_payload.get("type") in self._suppressed_events:
            return

        # Extract simulation_id from session state if available.
        # CallbackContext/ToolContext have a .state property directly.
        # InvocationContext (from run callbacks) has session.state instead.
        simulation_id = None
        try:
            ctx_state = getattr(context, "state", None)
            if ctx_state is None:
                # Fallback for InvocationContext which has session.state
                session_obj = getattr(context, "session", None)
                if session_obj is not None:
                    ctx_state = getattr(session_obj, "state", None)
            if ctx_state is not None:
                simulation_id = ctx_state.get("simulation_id")
        except Exception:
            pass

        # Fallback: check process-local simulation registry.
        # The dispatcher writes session→simulation at spawn time; this
        # lets DashLogPlugin find it even when the ADK session state
        # does not contain simulation_id (runner agents).
        if simulation_id is None:
            from agents.utils.simulation_registry import lookup

            simulation_id = await lookup(str(session_id) if session_id else "")

        event_type = payload.get("type")

        # DIAGNOSTIC: Log IDs for simulation_id mismatch debugging.
        # DEBUG level: fires per-event per-agent (hundreds/sec during sim),
        # so it must not block.  Enable with DEBUG log level when needed.
        if logger.isEnabledFor(logging.DEBUG) and event_type in (
            "run_start",
            "tool_start",
            "tool_end",
        ):
            logger.debug(
                "DASHLOG_IDS: event=%s session_id=%s simulation_id=%s agent=%s",
                event_type,
                session_id,
                simulation_id,
                safe_payload.get("agent"),
            )

        if self._fire_and_forget:
            # Non-blocking: wrap in background tasks for runner throughput
            asyncio.create_task(self._do_publish(context, safe_payload))
            if event_type in ("model_end", "tool_end", "model_error", "tool_error"):
                asyncio.create_task(self._emit_narrative(session_id, safe_payload, simulation_id=simulation_id))
            if event_type in ("model_start", "tool_start", "run_start", "run_end"):
                asyncio.create_task(self._emit_lifecycle_event(session_id, safe_payload, simulation_id=simulation_id))
        else:
            # Blocking: await each stage for planner/simulator correctness
            await self._do_publish(context, safe_payload)
            if event_type in ("model_end", "tool_end", "model_error", "tool_error"):
                await self._emit_narrative(session_id, safe_payload, simulation_id=simulation_id)
            if event_type in ("model_start", "tool_start", "run_start", "run_end"):
                await self._emit_lifecycle_event(session_id, safe_payload, simulation_id=simulation_id)

    async def _emit_narrative(
        self,
        session_id: str,
        payload: Dict[str, Any],
        simulation_id: str | None = None,
    ) -> None:
        """Extract elements and emit discrete gateway messages."""
        from agents.utils.pulses import emit_gateway_message

        agent_val = payload.get("agent") or "Agent"
        agent_id = str(agent_val)
        agent_display = self._display_names.get(agent_id, agent_id.replace("_agent", "").title())

        type_val = payload.get("type") or "event"
        event_type = str(type_val).replace("_", " ").title()

        preamble = f"[{agent_display}] {event_type}"
        if "tool" in payload:
            preamble += f": {payload['tool']}"

        try:
            raw_text = ""
            is_json_result = False
            if "response" in payload:
                # Prefer `response.text` (verbatim text-only, the chat
                # contract); fall back to `response.content` for any
                # legacy/test payload that still ships only the rich
                # summary field.
                response = payload["response"]
                if "text" in response:
                    raw_text = str(response["text"])
                elif "content" in response:
                    raw_text = str(response["content"])
            elif "result" in payload:
                res = payload["result"]
                if isinstance(res, dict):
                    raw_text = json.dumps(res)
                    is_json_result = True
                else:
                    raw_text = str(res)
            elif "error" in payload:
                err = payload["error"]
                if isinstance(err, dict):
                    raw_text = f"Error: {err.get('message', 'Unknown error')}"
                else:
                    raw_text = f"Error: {str(err)}"

            a2ui_blocks = []
            clean_text = raw_text

            # Try JSON extraction first
            try:
                parsed_json = json.loads(raw_text)
                if isinstance(parsed_json, dict) and "a2ui" in parsed_json:
                    a2ui_value = parsed_json.get("a2ui", "")

                    if isinstance(a2ui_value, (dict, list)):
                        # Tool returned a2ui as a parsed object (e.g. validate_and_emit_a2ui)
                        a2ui_blocks.append(json.dumps(a2ui_value))
                    else:
                        # Tool returned a2ui as a string -- apply cleanup
                        a2ui_content = str(a2ui_value).strip()

                        if a2ui_content.startswith("```a2ui"):
                            a2ui_content = a2ui_content[len("```a2ui") :].lstrip("\n")
                        if a2ui_content.endswith("```"):
                            a2ui_content = a2ui_content[:-3].rstrip("\n")

                        a2ui_content = a2ui_content.strip()
                        if a2ui_content.startswith("a2ui"):
                            a2ui_content = a2ui_content[4:].lstrip("\n{").lstrip()
                            if not a2ui_content.startswith("{"):
                                a2ui_content = "{" + a2ui_content

                        a2ui_blocks.append(a2ui_content.strip())

                    status = parsed_json.get("status", "")
                    clean_text = f"Status: {status}" if status else ""
                    is_json_result = False  # If it has a2ui, the remaining is just text
            except (json.JSONDecodeError, TypeError):
                # Non-JSON content (e.g. model text).  Strip any fenced
                # ```a2ui ... ``` blocks so the raw A2UI markup doesn't leak
                # into narrative text (the tool_end JSON path above is the
                # sole A2UI emission point).
                a2ui_strip_pattern = r"```a2ui\n[\s\S]*?(?:\n```|$)"
                clean_text = re.sub(a2ui_strip_pattern, "", raw_text).strip()
                if clean_text != raw_text.strip():
                    logger.debug(
                        "NARRATIVE_A2UI_STRIP: stripped a2ui fenced block from "
                        "model text; use validate_and_emit_a2ui tool for A2UI emission"
                    )

            origin = {"type": "agent", "id": agent_id, "session_id": session_id}

            # 1. Emit the standard text/json content if there's anything left
            final_text = preamble
            if clean_text:
                if is_json_result:
                    try:
                        parsed = json.loads(clean_text)

                        emit_event = type_val if type_val != "event" else "json"
                        emit_data = parsed

                        if "tool" in payload:
                            emit_data = {"tool_name": payload["tool"], "result": parsed}

                        # Optional gateway emission delay: any tool can
                        # set "gateway_delay_seconds" in its result to
                        # defer the frontend-visible event.
                        gw_delay = 0.0
                        if isinstance(parsed, dict):
                            gw_delay = parsed.pop("gateway_delay_seconds", 0.0)
                        if gw_delay > 0:
                            await asyncio.sleep(gw_delay)

                        await emit_gateway_message(
                            origin=origin,
                            destination=[session_id],
                            status="success",
                            msg_type="json",
                            event=emit_event,
                            data=emit_data,
                            simulation_id=simulation_id,
                        )
                        final_text = None
                    except Exception:
                        final_text += f"\n\n{clean_text}"
                else:
                    final_text += f"\n\n{clean_text}"

            # Gate on BOTH `clean_text` and `final_text`:
            # - `clean_text` (real content from the agent): without this,
            #   empty / function-call-only / a2ui-without-status turns would
            #   emit a preamble-only "[Agent] Model End" chat bubble because
            #   `final_text = preamble` is always truthy.
            # - `final_text` (set to None by the JSON path on success above):
            #   without this, a successful `tool_end` JSON emission would be
            #   followed by a stray text emission of the same content.
            # Wire `event` carries the source `type_val` (e.g. `model_end`,
            # `tool_end`). The frontend's chat is fed by the dispatcher's
            # passthrough at `agents/utils/dispatcher.py:624-666`, which
            # emits `event=text`; the FE silently drops everything else, so
            # emitting `event=text` here would cause duplicate chat messages
            # (one from us with the "[Agent] Model End" preamble, one clean
            # from the dispatcher). Keep the source type so the FE drop is
            # intentional.
            if clean_text and final_text:
                emit_event_text = type_val if type_val != "event" else "text"
                # Emit as Text
                await emit_gateway_message(
                    origin=origin,
                    destination=[session_id],
                    status="success",
                    msg_type="text",
                    event=emit_event_text,
                    data={"text": final_text},
                    simulation_id=simulation_id,
                )

            # 2. Emit each A2UI block individually
            for block in a2ui_blocks:
                # Use JSON stream decoding to robustly extract multiple objects
                # regardless of formatting (pretty-printed, JSONL, or mixed)
                decoder = json.JSONDecoder()
                pos = 0
                while pos < len(block):
                    # Find start of a potential JSON object/list
                    substring = block[pos:]
                    match = re.search(r"[\{\[]", substring)
                    if not match:
                        break

                    pos += match.start()
                    try:
                        a2ui_data, end_pos = decoder.raw_decode(block[pos:])
                        # ONLY emit if it's a dict or list (valid A2UI object)
                        if isinstance(a2ui_data, (dict, list)):
                            await emit_gateway_message(
                                origin=origin,
                                destination=[session_id],
                                status="success",
                                msg_type="a2ui",
                                event="a2ui",
                                data=a2ui_data,
                                simulation_id=simulation_id,
                            )
                        pos += end_pos
                    except (json.JSONDecodeError, ValueError):
                        # Skip this character and keep searching
                        pos += 1

        except Exception as e:
            logger.error(f"NARRATIVE_PULSE_ERROR: Failed to process narrative for {session_id}: {e}")

    async def _emit_lifecycle_event(
        self,
        session_id: str,
        payload: Dict[str, Any],
        simulation_id: str | None = None,
    ) -> None:
        """Emit a lifecycle event as a JSON message for frontend rendering."""
        from agents.utils.pulses import emit_gateway_message

        agent_val = payload.get("agent") or "Agent"
        agent_id = str(agent_val)
        event_type = str(payload.get("type", "event"))

        # Only allowlisted tool args are included (via _TOOL_DISPLAY_HINTS)
        # to keep start events lightweight and avoid leaking sensitive data.
        agent_display = self._display_names.get(agent_id, agent_id)
        data: Dict[str, Any] = {"agent": agent_display}
        if "model" in payload:
            data["model"] = str(payload["model"])
        if "tool" in payload:
            data["tool"] = str(payload["tool"])
            # Cherry-pick allowlisted args for display (secure-by-default).
            tool_name = data["tool"]
            hint_keys = _TOOL_DISPLAY_HINTS.get(tool_name)
            if hint_keys and "args" in payload:
                hints = {k: str(v) for k, v in payload["args"].items() if k in hint_keys and v is not None}
                if hints:
                    data["tool_hints"] = hints

        origin = {"type": "agent", "id": agent_id, "session_id": session_id}

        try:
            await emit_gateway_message(
                origin=origin,
                destination=[session_id],
                status="info",
                msg_type="json",
                event=event_type,
                data=data,
                simulation_id=simulation_id,
            )
        except Exception as e:
            logger.error(f"LIFECYCLE_EVENT_ERROR: Failed to emit {event_type} for {session_id}: {e}")


class RedisDashLogPlugin(BaseDashLogPlugin):
    """Plugin that emits telemetry events via Redis broadcast AND Pub/Sub."""

    def __init__(self, topic_id: Optional[str] = None, agent_display_names: dict[str, str] | None = None, **kwargs):
        self._topic_id_override = topic_id
        super().__init__(name="redis_dash_log", agent_display_names=agent_display_names, **kwargs)

    def _init_transport(self) -> None:
        load_dotenv()
        self.project_id = os.getenv("PUBSUB_PROJECT_ID", "test-project")
        self.topic_id = self._topic_id_override or os.getenv("PUBSUB_TOPIC_ID", "agent-telemetry")
        self.topic_path = f"projects/{self.project_id}/topics/{self.topic_id}"

        batch_settings = pubsub_v1.types.BatchSettings(max_messages=10, max_bytes=1024, max_latency=1.0)

        try:
            self.publisher = pubsub_v1.PublisherClient(batch_settings=batch_settings)
            logger.info(f"REDIS_DASH_INIT: Dual-emission enabled (Redis + Pub/Sub: {self.topic_id})")
        except Exception as e:
            logger.error(f"REDIS_DASH_INIT_ERROR: Failed to create Pub/Sub client: {e}")
            self.publisher = None

    async def _do_publish(self, context: Any, payload: Dict[str, Any]) -> None:
        """Publish via Pub/Sub. Redis narrative messages are handled by the _publish wrapper."""

        # 2. Pub/Sub (Agent Debug Log)
        if self.publisher:
            try:
                data = _safe_json_dumps(payload).encode("utf-8")
                self.publisher.publish(self.topic_path, data)
            except Exception as e:
                logger.error(f"TELEMETRY_PUBSUB_ERROR: {e}")
