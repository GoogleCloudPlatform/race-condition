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

"""Simulation A2A Executor — custom AgentExecutor for Agent Engine deployment.

Uses the a2a-sdk AgentExecutor base (NOT ADK's A2aAgentExecutor) to handle
session creation correctly via SessionManager.  Pattern from the working
next26-simulation-demos/demo-2-autonomous-agents reference implementation.

ADK's A2aAgentExecutor._prepare_session() is broken for VertexAiSessionService:
- Without context_id: get_session(None) → 400 Invalid Session resource name
- With context_id: get_session(404) → create_session(id=...) → ValueError

This executor bypasses _prepare_session entirely by managing sessions itself.
"""

import json
import logging
import os
import uuid
from typing import Any, Callable, Optional, cast

import vertexai

# CRITICAL FIX for Vertex AI Agent Engine:
# Agent Engine platforms set GOOGLE_CLOUD_PROJECT to the numeric Project ID.
# The google-cloud-aiplatform SDK's Initializer fails to convert this back to
# a string ID without excessive permissions, causing hangs.
# We override it globally here at import time to pre-empt the Initializer.
_pid = os.environ.get("PROJECT_ID")
if _pid:
    os.environ["GOOGLE_CLOUD_PROJECT"] = _pid
    os.environ["VERTEXAI_PROJECT"] = _pid
from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.tasks import TaskUpdater  # noqa: E402
from a2a.types import TaskState, TextPart, UnsupportedOperationError  # noqa: E402
from a2a.utils import new_agent_text_message  # noqa: E402
from a2a.utils.errors import ServerError  # noqa: E402
from google.adk import Runner  # noqa: E402
from google.genai import types  # noqa: E402

from agents.utils import pulses  # noqa: E402
from agents.utils import simulation_registry  # noqa: E402
from agents.utils.runtime import create_services  # noqa: E402
from agents.utils.session_manager import SessionManager  # noqa: E402

logger = logging.getLogger(__name__)


class SimulationExecutor(AgentExecutor):
    """Custom A2A executor for simulation agents deployed to Agent Engine.

    Features:
    - VertexAI Session Service for persistent conversation history
    - SessionManager with TTL cache mapping context_id → session_id
    - Proper session creation (without user-provided IDs)
    """

    def __init__(
        self,
        agent_getter: Callable[[], Any],
        agent_name: str,
        default_user_id: str = "simulation_user",
    ) -> None:
        # Fix for google/adk-python#3628: A2aAgent.set_up() (a2a.py line 240)
        # UNCONDITIONALLY overwrites GOOGLE_CLOUD_LOCATION to the AE region
        # (us-central1). Gemini 3 models require the global endpoint.
        # This __init__ runs at a2a.py line 250, AFTER the overwrite,
        # so we can safely re-set it here.
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

        # Explicitly set VERTEXAI_PROJECT and VERTEXAI_LOCATION for LiteLlm
        # and underlying SDKs, bypassing platform-reserved GOOGLE_CLOUD_PROJECT
        # numeric ID overrides.
        if "PROJECT_ID" in os.environ:
            os.environ["VERTEXAI_PROJECT"] = os.environ["PROJECT_ID"]
        if "AGENT_ENGINE_LOCATION" in os.environ:
            os.environ["VERTEXAI_LOCATION"] = os.environ["AGENT_ENGINE_LOCATION"]
        elif "GOOGLE_CLOUD_LOCATION" in os.environ:
            os.environ["VERTEXAI_LOCATION"] = os.environ["GOOGLE_CLOUD_LOCATION"]

        self._agent_getter = agent_getter
        self._agent_name = agent_name
        self._default_user_id = default_user_id
        self._runner: Optional[Runner] = None
        self._session_manager: Optional[SessionManager] = None
        self._dispatch_mode = os.environ.get("DISPATCH_MODE", "subscriber")

    def _init_runner(self) -> None:
        """Lazy initialization of the ADK Runner with correct services."""
        if self._runner is not None:
            return

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        # Gemini 3 models require the `global` endpoint (not us-central1).
        # GOOGLE_CLOUD_LOCATION controls model routing; AGENT_ENGINE_LOCATION
        # controls session service separately in runtime.py.
        model_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

        if project_id:
            vertexai.init(project=project_id, location=model_location)

        from agents.utils.plugins import RedisDashLogPlugin
        from agents.utils.simulation_plugin import SimulationNetworkPlugin
        from google.adk.apps import App

        agent = self._agent_getter()
        services = create_services()

        # Wire the same plugin stack as the factory (factory.py)
        orchestration_plugin = SimulationNetworkPlugin(name=self._agent_name)
        plugins = [RedisDashLogPlugin(), orchestration_plugin]

        app = App(
            name=self._agent_name,
            root_agent=agent,
            plugins=plugins,
        )

        self._runner = Runner(
            app=app,
            session_service=services.session_service,
            memory_service=services.memory_service,
        )

        # Wire orchestration
        orchestration_plugin.set_runner(self._runner)

        self._session_manager = SessionManager(
            session_service=self._runner.session_service,
            cache_maxsize=1000,
        )

        logger.info(
            "SimulationExecutor initialized: agent=%s, session=%s",
            self._agent_name,
            type(services.session_service).__name__,
        )

        # Ensure logging is configured for environments (like Agent Engine)
        # where no handler is set up by default. Without this, all INFO/DEBUG
        # logs are silently dropped by Python's lastResort handler.
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(name)s %(levelname)s %(message)s",
            )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute a request from the A2A protocol."""
        self._init_runner()
        assert self._runner is not None
        assert self._session_manager is not None

        user_id: str = (
            context.message.metadata.get("user_id") if context.message and context.message.metadata else None
        ) or self._default_user_id

        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        updater = TaskUpdater(event_queue, task_id, context_id)

        if not hasattr(context, "current_task") or not context.current_task:
            await updater.submit()

        await updater.start_work()

        query = context.get_user_input()
        if not query:
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message("No request provided"),
                final=True,
            )
            return

        logger.info("%s received: %s...", self._agent_name, query[:100])

        # ORCHESTRATION INTERCEPTION:
        # Detect if this is a simulation orchestration event (Pulse or Spawn)
        # sent via A2A message/send.
        dispatch_mode = self._dispatch_mode

        # Track simulation_id extracted from orchestration events so it can
        # be bridged to the Vertex AI session created later.  Locally this
        # mapping is written by the RedisOrchestratorDispatcher; on AE in
        # callable mode the dispatcher idles, so we must do it here.
        _event_simulation_id: str | None = None

        try:
            event = json.loads(query)
            if isinstance(event, dict) and "type" in event:
                event_type = event.get("type")
                logger.info(
                    "SIMULATION_EXECUTOR: Intercepted orchestration event: %s (mode=%s)", event_type, dispatch_mode
                )

                # Extract simulation_id from event payload (set by gateway
                # spawn handler in cmd/gateway/main.go).
                _evt_payload = event.get("payload")
                if isinstance(_evt_payload, dict):
                    _event_simulation_id = _evt_payload.get("simulation_id")

                if dispatch_mode == "callable":
                    # CALLABLE MODE (Agent Engine): Handle directly without dispatcher.
                    # The dispatcher uses per-process in-memory session tracking which
                    # breaks across AE's multi-worker deployment. Instead, we handle
                    # events directly and use SessionManager + VertexAiSessionService
                    # for session continuity (shared across all workers).
                    if event_type == "spawn_agent":
                        payload = event.get("payload", {})
                        target_type = payload.get("agentType")

                        # Register session→simulation mapping in Redis so
                        # that subsequent broadcast events (which may land on
                        # a different AE instance) can resolve simulation_id
                        # for DashLogPlugin.
                        if _event_simulation_id and context_id:
                            await simulation_registry.register(context_id, _event_simulation_id)
                            logger.info(
                                "SIMULATION_EXECUTOR: Registered simreg %s → %s (spawn)",
                                context_id,
                                _event_simulation_id,
                            )

                        if target_type == self._agent_name:
                            logger.info("SIMULATION_EXECUTOR: Acknowledged spawn for %s", self._agent_name)
                        else:
                            logger.info(
                                "SIMULATION_EXECUTOR: Ignored spawn for %s (we are %s)", target_type, self._agent_name
                            )
                        await updater.complete()
                        return

                    elif event_type == "broadcast":
                        # Extract user text from broadcast payload and fall through
                        # to the direct execution path below.
                        payload = event.get("payload", {})
                        broadcast_data = payload.get("data", "")
                        try:
                            inner = json.loads(broadcast_data)
                            if isinstance(inner, dict) and "text" in inner:
                                query = inner["text"]
                            else:
                                query = broadcast_data
                        except (json.JSONDecodeError, TypeError):
                            query = broadcast_data
                        if not query:
                            logger.warning("SIMULATION_EXECUTOR: Broadcast had empty text, skipping execution")
                            await updater.complete()
                            return
                        logger.info("SIMULATION_EXECUTOR: Extracted broadcast text: %s...", query[:80])
                        # Fall through to direct execution path below
                    else:
                        # Unknown event type in callable mode — acknowledge
                        logger.warning("SIMULATION_EXECUTOR: Unknown event type %s, acknowledging", event_type)
                        await updater.complete()
                        return
                else:
                    # SUBSCRIBER MODE (Cloud Run): Use dispatcher-based path.
                    from agents.utils.simulation_plugin import SimulationNetworkPlugin

                    orchestration_plugin = next(
                        (p for p in getattr(self._runner.app, "plugins", []) if isinstance(p, SimulationNetworkPlugin)),
                        None,
                    )
                    if orchestration_plugin and orchestration_plugin.dispatcher:
                        await orchestration_plugin.dispatcher.handle_event(event)
                        await updater.complete()
                        return
                    else:
                        logger.warning("SIMULATION_EXECUTOR: No dispatcher found for intercepted event")
        except (json.JSONDecodeError, TypeError):
            # Not a JSON event, proceed as normal user query
            pass

        try:
            await updater.update_status(
                TaskState.working,
                message=new_agent_text_message("Processing request..."),
            )

            # Session creation via SessionManager — correctly calls
            # create_session() WITHOUT user-provided session_id
            session_id = await self._session_manager.get_or_create_session(
                context_id=context_id,
                app_name=self._runner.app_name,
                user_id=user_id,
            )

            # SESSION ID BRIDGE (callable mode):
            # On AE, VertexAiSessionService generates internal session IDs
            # (e.g. '40765115') that differ from the gateway's spawn session
            # UUIDs (e.g. 'a8df62fd-...').  The frontend filters events by
            # the spawn UUID, so events with Vertex IDs are invisible.
            #
            # Register the reverse mapping so DashLogPlugin can emit events
            # with the original spawn session ID in the origin field.
            if session_id != context_id:
                await simulation_registry.register_context(session_id, context_id)
                logger.info(
                    "SIMULATION_EXECUTOR: Registered context mapping %s (vertex) → %s (spawn)",
                    session_id,
                    context_id,
                )

            # SIMULATION_ID BRIDGE:
            # Bridge simulation_id from orchestration context to Vertex session.
            simulation_id = _event_simulation_id
            if not simulation_id:
                simulation_id = await simulation_registry.lookup(context_id)
            if simulation_id and session_id != context_id:
                await simulation_registry.register(session_id, simulation_id)
                logger.info(
                    "SIMULATION_EXECUTOR: Bridged simreg %s (context) → %s (vertex) = %s",
                    context_id,
                    session_id,
                    simulation_id,
                )

            content = types.Content(
                role="user",
                parts=[types.Part(text=query)],
            )

            final_event = None
            async for event in self._runner.run_async(
                session_id=session_id,
                user_id=user_id,
                new_message=content,
            ):
                if event.is_final_response():
                    final_event = event

                # TELEMETRY BRIDGE:
                # Direct A2A calls skip the Redis listener that usually broadcasts
                # narrative pulses. We bridge them here so the dashboard stays updated.
                # Use context_id (spawn UUID) instead of vertex session_id so the
                # frontend's session-based rendering filters match.
                origin_session = context_id if context_id != session_id else session_id
                if event.author in ["agent", "model", self._agent_name]:
                    if event.content and event.content.parts:
                        for p in event.content.parts:
                            text = getattr(p, "text", None)
                            if text:
                                await pulses.emit_gateway_message(
                                    origin={
                                        "type": "agent",
                                        "id": self._agent_name,
                                        "session_id": origin_session,
                                    },
                                    destination=[origin_session],
                                    status="success",
                                    msg_type="json",
                                    event="narrative",
                                    data={"text": text, "emotion": "neutral"},
                                    simulation_id=simulation_id,
                                )

            if final_event and final_event.content and final_event.content.parts:
                response_text = "".join(
                    part.text for part in final_event.content.parts if hasattr(part, "text") and part.text
                )

                if response_text:
                    await updater.add_artifact(
                        cast(list, [TextPart(text=response_text)]),
                        name=f"{self._agent_name}_result",
                    )
                    await updater.complete()
                    return

            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"{self._agent_name} failed to generate response"),
                final=True,
            )

        except Exception as e:
            logger.error("%s error: %s", self._agent_name, e, exc_info=True)
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"Request failed: {str(e)[:200]}"),
                final=True,
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())
