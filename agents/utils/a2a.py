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

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import FastAPI
from a2a.types import AgentCard
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.agents.base_agent import BaseAgent
from google.adk.apps import App
from google.adk.runners import Runner

logger = logging.getLogger(__name__)


def expand_env_vars(data: Any) -> Any:
    """Recursively expand ${VAR} placeholders in strings using environment variables."""
    if isinstance(data, str):

        def replace_match(m):
            var_name = m.group(1)
            val = os.environ.get(var_name)
            if val is None:
                logger.warning(f"ENV_EXPANSION: Variable ${var_name} not found in environment, leaving placeholder.")
                return m.group(0)
            return val

        return re.sub(r"\$\{([^}]+)\}", replace_match, data)
    elif isinstance(data, list):
        return [expand_env_vars(item) for item in data]
    elif isinstance(data, dict):
        return {key: expand_env_vars(value) for key, value in data.items()}
    return data


def prepare_simulation_agent(
    agent_or_app: Union[BaseAgent, App],
    agents_dir: Union[str, Path],
    skills: list | None = None,
) -> AgentCard:
    """
    Generates an AgentCard using AgentCardBuilder and attaches it to the agent instance.
    """
    if isinstance(agent_or_app, App):
        agent = agent_or_app.root_agent
        app_name = agent_or_app.name
    else:
        agent = agent_or_app
        app_name = getattr(agent, "name", "unknown")

    # Build the rpc_url from the base URL + the mount prefix.
    # Starlette mounts the sub-app at /a2a/{name}, so the actual RPC
    # endpoint is /a2a/{name}/ (trailing slash required by Starlette).
    base_url = os.environ.get(f"{app_name.upper()}_URL", "").rstrip("/")
    rpc_url = f"{base_url}/a2a/{app_name}/" if base_url else ""

    # Use vertexai's sync create_agent_card() instead of async
    # AgentCardBuilder.build(). Agent Engine unpickles agent modules
    # inside uvicorn (running event loop), so asyncio.run() crashes.
    from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card

    # Use explicitly passed skills, or fall back to agent's skills attribute
    if not skills:
        agent_skills = getattr(agent, "skills", None)
        if agent_skills:
            from a2a.types import AgentSkill as A2ASkill

            skills = []
            for s in agent_skills:
                if isinstance(s, A2ASkill):
                    skills.append(s)
                elif isinstance(s, dict):
                    skills.append(A2ASkill(**s))

    # create_agent_card requires at least one skill — create a default
    if not skills:
        from a2a.types import AgentSkill as A2ASkill

        skills = [
            A2ASkill(
                id=f"{app_name}_default",
                name=app_name,
                description=getattr(agent, "description", None) or f"{app_name} agent",
                tags=[app_name, "simulation"],
            )
        ]

    agent_card = create_agent_card(
        agent_name=app_name,
        description=getattr(agent, "description", None) or f"{app_name} agent",
        skills=skills,
    )
    # Set URL separately — create_agent_card doesn't accept url param
    if rpc_url:
        agent_card.url = rpc_url
    tags = getattr(agent, "tags", [])

    # Note: AgentCardBuilder strips the trailing slash from rpc_url, but
    # Starlette mount requires it. Add it back so the card URL matches the
    # actual endpoint. Without this, A2A clients hit /a2a/{name} which
    # triggers a 307 redirect to /a2a/{name}/ that most clients don't follow.
    if agent_card.url and not agent_card.url.endswith("/"):
        agent_card.url += "/"
    logger.info(f"Card URL for {app_name}: {agent_card.url}")

    # Validate URL scheme to prevent orchestration 404s/protocol errors
    if agent_card.url:
        if not (agent_card.url.startswith("http://") or agent_card.url.startswith("https://")):
            logger.error(
                f"A2A_VALIDATION_ERROR: Agent {app_name} has invalid URL scheme "
                f"in '{agent_card.url}'. Must start with http:// or https://."
            )
            # We don't crash, but orchestration will likely fail until fixed.
        else:
            logger.info(f"A2A_VALIDATION: Agent {app_name} URL verified: {agent_card.url}")

    # Inject A2UI Extension if applicable
    # Scan all skills for 'a2ui' tag
    has_a2ui_skill = False
    for skill in getattr(agent_card, "skills", []) or []:
        s_tags = skill.get("tags", []) if isinstance(skill, dict) else getattr(skill, "tags", []) or []
        if "a2ui" in s_tags:
            has_a2ui_skill = True
            break

    if "a2ui" in (tags or []) or has_a2ui_skill:
        if not agent_card.capabilities:
            from a2a.types import AgentCapabilities

            agent_card.capabilities = AgentCapabilities(streaming=True)
        else:
            # Force streaming to true for A2UI agents as per best practices
            agent_card.capabilities.streaming = True

        extensions = agent_card.capabilities.extensions or []
        a2ui_ext_uri = "a2ui:json/1.0"

        # Check if already injected or needing update
        ext = next((e for e in extensions if e.uri == a2ui_ext_uri), None)
        if not ext:
            from a2a.types import AgentExtension

            ext = AgentExtension(uri=a2ui_ext_uri, params={})
            extensions.append(ext)
            agent_card.capabilities.extensions = extensions

        # Standardize params
        if ext.params is None:
            ext.params = {}
        ext.params.update({"supported_catalog_ids": ["a2ui:standard/1.0"]})
        # Remove old/deprecated fields if they exist
        ext.params.pop("accepts_inline_catalogs", None)

        logger.info(f"Standardized A2UI Extension for {app_name} in AgentCard")

    # Inject n26:dispatch/1.0 extension based on DISPATCH_MODE env var.
    # Tells the gateway switchboard how to route events to this agent:
    #   - "subscriber": HTTP POST /orchestration poke (Cloud Run agents)
    #   - "callable": A2A JSON-RPC message/send (Agent Engine agents)
    dispatch_mode = os.getenv("DISPATCH_MODE", "subscriber")

    if not agent_card.capabilities:
        from a2a.types import AgentCapabilities

        agent_card.capabilities = AgentCapabilities(streaming=True)

    extensions = agent_card.capabilities.extensions or []
    dispatch_ext = next((e for e in extensions if e.uri == "n26:dispatch/1.0"), None)
    if not dispatch_ext:
        from a2a.types import AgentExtension

        dispatch_ext = AgentExtension(uri="n26:dispatch/1.0", params={})
        extensions.append(dispatch_ext)
        agent_card.capabilities.extensions = extensions
    if dispatch_ext.params is None:
        dispatch_ext.params = {}
    dispatch_ext.params["mode"] = dispatch_mode
    logger.info(f"A2A_CARD: Injected dispatch extension: mode={dispatch_mode}")

    # Attach to the agent instance for Agent Engine discovery
    object.__setattr__(agent, "agent_card", agent_card)
    logger.info(f"Attached AgentCard to {app_name} (URL: {agent_card.url})")

    return agent_card


def register_a2a_routes(
    app: FastAPI,
    agent_or_app: Union[BaseAgent, App],
    agent_card: AgentCard,
    path_prefix: str = "",
    simulation_runner: Optional[Runner] = None,
):
    """
    Manually registers A2A routes for a local FastAPI server using the provided AgentCard.

    Args:
        simulation_runner: If provided, use this Runner for orchestration dispatch
            instead of creating a throwaway one.  This preserves the session service
            and auto_create_session settings from create_simulation_runner().
    """
    app_name = agent_card.name
    # Ensure path_prefix starts and ends correctly for mounting
    if path_prefix and not path_prefix.startswith("/"):
        path_prefix = "/" + path_prefix
    path_prefix = path_prefix.rstrip("/")

    from fastapi.responses import JSONResponse
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    app_instance = agent_or_app if isinstance(agent_or_app, App) else App(root_agent=agent_or_app, name=app_name)
    if simulation_runner is None:
        simulation_runner = Runner(app=app_instance, session_service=InMemorySessionService())

    async def get_runner():
        return simulation_runner

    agent_executor = A2aAgentExecutor(runner=get_runner)
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(agent_executor=agent_executor, task_store=task_store)

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # 1. Identity & Health (Root)
    app.add_route("/.well-known/agent-card.json", a2a_app._handle_get_agent_card, methods=["GET"])

    async def app_health(request):
        return JSONResponse(content={"status": "ok", "app": app_name})

    app.add_route("/health", app_health, methods=["GET"])

    # Build the A2A sub-application unconditionally
    sub_app = a2a_app.build()

    # 2. Orchestration (Hybrid - both root and prefix for compatibility)
    from agents.utils.simulation_plugin import SimulationNetworkPlugin

    orchestration_plugin = next(
        (p for p in getattr(app_instance, "plugins", []) if isinstance(p, SimulationNetworkPlugin)),
        None,
    )
    if orchestration_plugin:
        orchestration_plugin.set_runner(simulation_runner)

        async def handle_orchestration(request):
            data = await request.json()
            if orchestration_plugin.dispatcher:
                logger.debug(f"A2A_ORCHESTRATION: Pushed event for {app_name}")
                await orchestration_plugin.dispatcher.handle_event(data)
                return JSONResponse(content={"status": "success"})
            return JSONResponse(content={"status": "error", "message": "No dispatcher"}, status_code=500)

        app.add_route("/orchestration", handle_orchestration, methods=["POST"])
        sub_app.add_route("/orchestration", handle_orchestration, methods=["POST"])

    # 3. Mount A2A RPC at prefix
    mount_path = f"{path_prefix}/" if path_prefix else "/"
    logger.info(f"Mounting A2A RPC for {app_name} at {mount_path}")

    # Add health check to sub-app for admin dashboard monitoring
    async def sub_app_health(request):
        return JSONResponse(content={"status": "ok", "app": app_name})

    sub_app.add_route("/health", sub_app_health, methods=["GET"])

    # Add CORS to the mounted sub_app as well, as it might be accessed directly
    from fastapi.middleware.cors import CORSMiddleware

    sub_app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount(mount_path, sub_app)

    # Ensure CORS is on the main app too
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"Successfully mounted A2A sub-app for {app_name} at {mount_path}")
