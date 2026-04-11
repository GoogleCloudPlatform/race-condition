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

"""Unified agent serving — centralizes CORS, health, A2A, and uvicorn config.

Provides a single entry point for all Python agents to serve themselves with
correct GCLB proxy headers, health endpoints, CORS, and A2A routing.

Usage (in each agent's __main__):

    from agents.utils.serve import create_agent_app, serve_agent

    api_app = create_agent_app(
        name="simulator",
        agents_dir="agents/simulator",
        adk_app=app,
        agent_card=agent_card,
    )
    serve_agent(api_app, port=8202)
"""

import logging
import os

import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from google.adk.cli.fast_api import get_fast_api_app

from agents.utils.a2a import register_a2a_routes

logger = logging.getLogger(__name__)


def create_agent_app(
    name: str,
    agents_dir: str,
    adk_app,
    agent_card,
    simulation_runner=None,
):
    """Create a FastAPI app with standard middleware, health, and A2A routes.

    This centralizes all boilerplate that was previously duplicated across
    every agent's __main__ block: CORS, health endpoints, A2A routing.

    Args:
        name: Agent name (used in health response).
        agents_dir: Path to agents directory for get_fast_api_app.
        adk_app: The ADK App instance.
        agent_card: The A2A AgentCard for route registration.
        simulation_runner: Optional Runner from create_simulation_runner().
            If provided, the /orchestration endpoint uses this runner
            (preserving DatabaseSessionService + auto_create_session).

    Returns:
        A fully configured FastAPI application.
    """
    api_app = get_fast_api_app(agents_dir=agents_dir, a2a=False, web=False)

    # CORS — read allowed origins from env var (comma-separated).
    # Defaults to "*" for local dev parity; cloud sets specific origins.
    cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
    api_app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_a2a(api_app, adk_app, agent_card, name, simulation_runner)

    # Note: /health endpoint is provided by get_fast_api_app() (returns {"status": "ok"})

    return api_app


def _register_a2a(api_app, adk_app, agent_card, name, simulation_runner=None):
    """Internal helper to register A2A routes, isolated for testing."""
    # Use agent name as the mount prefix to match Gateway routing: /a2a/{name}/

    register_a2a_routes(api_app, adk_app, agent_card, path_prefix=f"/a2a/{name}", simulation_runner=simulation_runner)


def serve_agent(app, port: int):
    """Run uvicorn with GCLB-compatible proxy headers.

    Args:
        app: The FastAPI application to serve.
        port: Port number to bind to.
    """
    logger.info("Starting agent on port %d with proxy_headers=True", port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
