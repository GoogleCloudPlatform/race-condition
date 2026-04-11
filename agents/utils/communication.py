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

import json
import os
import time
import httpx
import logging
import asyncio
from typing import Optional, Dict, Any, Union
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from a2a.client.client import ClientConfig as A2AClientConfig
from a2a.client.client_factory import ClientFactory as A2AClientFactory
from a2a.types import (
    AgentCard,
    TransportProtocol,
    Part,
    TextPart,
    Role,
    Message as A2AMessage,
    AgentCapabilities,
)
from agents.utils import config
from google.adk.tools.tool_context import ToolContext
from agents.utils.pulses import emit_inter_agent_pulse

logger = logging.getLogger(__name__)

# Module-level discovery cache (shared across all SimulationA2AClient instances)
_discovery_cache: dict[str, Any] = {}
_discovery_cache_ts: float = 0.0
_DISCOVERY_CACHE_TTL: float = 30.0  # Match gateway's 30s TTL

# Shared httpx client for agent discovery
_discovery_client: httpx.AsyncClient | None = None


def _get_discovery_client() -> httpx.AsyncClient:
    """Get or create a shared httpx client for discovery calls.

    Thread-safety: This runs on a single asyncio event loop. The check-and-set
    has no `await` in between, so there is no concurrent initialization risk
    within the same event loop. The client intentionally lives for the process
    lifetime (no close).
    """
    global _discovery_client
    if _discovery_client is None:
        _discovery_client = httpx.AsyncClient(timeout=5.0)
    return _discovery_client


def _is_agent_engine_url(url: str) -> bool:
    """Return True if the URL points to a Vertex AI Agent Engine resource."""
    return "aiplatform.googleapis.com" in url and "reasoningEngines" in url


class _GCPAuth(httpx.Auth):
    """httpx auth handler that injects GCP OAuth2 credentials.

    Refreshes the token on every request so long-running simulation
    pipelines never hit expired-token errors.
    """

    def __init__(self):
        import google.auth
        import google.auth.transport.requests

        self._credentials, _ = google.auth.default()
        self._request = google.auth.transport.requests.Request()

    def auth_flow(self, request):
        self._credentials.refresh(self._request)
        request.headers["Authorization"] = f"Bearer {self._credentials.token}"
        yield request


class SimulationA2AClient:
    """
    Standardized client for inter-agent communication in the N26 Simulation.
    Handles discovery via the Gateway and resilience for scale-to-zero.
    """

    def __init__(self, gateway_url: Optional[str] = None):
        config.load_env()
        # Prefer GATEWAY_INTERNAL_URL (Cloud Run internal, bypasses IAP) over
        # GATEWAY_URL (public/IAP-fronted). AE agents can reach the internal
        # URL via VPC/PSC but cannot authenticate through IAP.
        self.gateway_url = (
            gateway_url
            or os.environ.get("GATEWAY_INTERNAL_URL")
            or config.optional("GATEWAY_URL", "http://localhost:8101")
        )
        self._registry_cache: Dict[str, AgentCard] = {}
        self._agents: Dict[str, RemoteA2aAgent] = {}

    async def _discover_agents(self) -> Dict[str, AgentCard]:
        """Fetch all available agent types from the Gateway registry.

        Uses a module-level cache with a 30s TTL to avoid redundant HTTP calls
        across SimulationA2AClient instances within the same process.
        """
        global _discovery_cache, _discovery_cache_ts
        now = time.monotonic()
        if _discovery_cache and (now - _discovery_cache_ts) < _DISCOVERY_CACHE_TTL:
            self._registry_cache = _discovery_cache
            return _discovery_cache

        url = f"{self.gateway_url}/api/v1/agent-types"
        try:
            client = _get_discovery_client()
            resp = await client.get(url, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()

            cards = {}
            for name, card_data in data.items():
                # Use model_validate to handle camelCase→snake_case alias
                # resolution (e.g., additionalInterfaces, preferredTransport)
                cards[name] = AgentCard.model_validate(card_data)

            _discovery_cache = cards
            _discovery_cache_ts = now
            self._registry_cache = cards
            logger.info(f"A2A_DISCOVERY: Discovered {len(cards)} agent types from Gateway.")
            return cards
        except Exception as e:
            logger.error(f"A2A_DISCOVERY_ERROR: Failed to fetch agent types from {url}: {e}")
            return self._registry_cache

    async def get_agent(self, name: str, force_refresh: bool = False) -> RemoteA2aAgent:
        """Resolve an agent name to a RemoteA2aAgent instance."""
        if name in self._agents and not force_refresh:
            return self._agents[name]

        registry = await self._discover_agents()
        if name not in registry:
            # Fallback to env var if not in registry.
            # Check both {NAME}_URL and {NAME}_INTERNAL_URL (AE deployments
            # use INTERNAL_URL format).
            url = os.environ.get(f"{name.upper()}_URL") or os.environ.get(f"{name.upper()}_INTERNAL_URL")
            if not url:
                raise ValueError(f"Agent '{name}' not found in registry and no {name.upper()}_URL provided.")

            logger.warning(f"A2A_DISCOVERY: Agent '{name}' not in registry, using env URL: {url}")
            # Determine URL and transport based on whether this is an AE agent.
            is_ae = _is_agent_engine_url(url)
            if is_ae:
                # AE agents: append /a2a so RestTransport constructs the
                # correct path: {base}/a2a/v1/message:send (not /v1/message:send).
                a2a_url = f"{url.rstrip('/')}/a2a"
                transport = TransportProtocol.http_json
            else:
                # Local/Cloud Run: append the A2A mount path convention.
                # This matches the server's mount point in agents/utils/serve.py.
                a2a_url = f"{url.rstrip('/')}/a2a/{name}/"
                transport = TransportProtocol.jsonrpc
            card = AgentCard(
                name=name,
                url=a2a_url,
                description=f"Fallback for {name}",
                version="1.0.0",
                capabilities=AgentCapabilities(),
                default_input_modes=["text/plain"],
                default_output_modes=["text/plain"],
                skills=[],
                preferred_transport=transport,
            )
        else:
            card = registry[name]

        # Local/Cloud Run agents use JSON-RPC protocol (A2AStarletteApplication).
        # The Vertex AI SDK forces http_json on AgentCards, but that's the REST
        # transport which appends /v1/message:send — local servers don't serve that.
        # Only normalize to jsonrpc for non-AE agents. AE agents need http_json
        # because Agent Engine serves the REST transport at /a2a/v1/message:send.
        if _is_agent_engine_url(card.url or ""):
            # Ensure AE card URLs include the /a2a prefix so RestTransport
            # constructs {base}/a2a/v1/message:send (not /v1/message:send).
            if not (card.url or "").rstrip("/").endswith("/a2a"):
                card.url = f"{(card.url or '').rstrip('/')}/a2a"
        else:
            card.preferred_transport = TransportProtocol.jsonrpc

        # Build a ClientFactory that supports both jsonrpc and http_json
        # so that any server transport preference is compatible.
        # Simulation pipelines (e.g., simulator execute) can run for minutes.
        # 300s covers 24 ticks * 5s sleep + LLM overhead with margin.
        is_ae = _is_agent_engine_url(card.url or "")
        httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=300.0),
            auth=_GCPAuth() if is_ae else None,
        )
        client_config = A2AClientConfig(
            httpx_client=httpx_client,
            streaming=False,
            polling=False,
            supported_transports=[
                TransportProtocol.jsonrpc,
                TransportProtocol.http_json,
            ],
        )
        factory = A2AClientFactory(config=client_config)

        agent = RemoteA2aAgent(
            name=name,
            agent_card=card,
            a2a_client_factory=factory,
            timeout=300.0,  # Long timeout: simulation pipelines take minutes
        )
        self._agents[name] = agent
        return agent

    async def call_agent(
        self,
        agent_name: str,
        message: Union[str, Dict[str, Any]],
        retries: int = 3,
        backoff: float = 1.5,
        session_id: Optional[str] = None,
    ) -> Any:
        """
        Call a remote agent with retry logic for scale-to-zero resilience.

        Args:
            agent_name: Name of the agent to call (e.g., 'runner').
            message: The message string or JSON dict to send.
            retries: Number of retries for 5xx or connection errors.
            backoff: Backoff multiplier for retries.
        """
        agent = await self.get_agent(agent_name)

        # Prepare parts
        if isinstance(message, dict):
            text = json.dumps(message)
        else:
            text = str(message)

        attempt = 0
        last_error = None

        while attempt <= retries:
            try:
                # We use a simple message exchange pattern for simulation tools.
                # Standard A2A flow via run_async is preferred for full history.
                # However, for simple tool-base probes, we use send_message directly.

                # ADK RemoteA2aAgent manages history internally if we use its higher level APIs.
                # For this utility, we'll provide a simplified 'request-response' wrapper.

                # Setup A2AMessage for a direct call
                from uuid import uuid4

                a2a_msg = A2AMessage(
                    message_id=str(uuid4()),
                    parts=[Part(root=TextPart(text=text))],
                    role=Role.user,
                    context_id=session_id,
                )

                # Ensure resolved (resolves HTTPS client etc)
                await agent._ensure_resolved()

                full_res_text = ""
                async for event in agent._a2a_client.send_message(a2a_msg):
                    # Technical telemetry is now fired directly by the callee agent
                    # using the RedisDashLogPlugin. We no longer relay it here.

                    # Handle both Message response (direct) and tuple (task, update) response (task-based)
                    msg = None
                    if isinstance(event, tuple):
                        task, update = event
                        if update is None:
                            # Initial task state, might have a Message in status
                            status = getattr(task, "status", None)
                            if status and getattr(status, "message", None):
                                msg = getattr(status, "message", None)
                            elif hasattr(task, "history") and task.history:
                                # Fallback: last agent message in history
                                agent_msgs = [
                                    m for m in task.history if hasattr(m, "role") and getattr(m, "role", "") == "agent"
                                ]
                                if agent_msgs:
                                    msg = agent_msgs[-1]

                            # Fallback: check task artifacts (A2aAgentExecutor
                            # puts the final response here, not in status.message)
                            if not msg and hasattr(task, "artifacts") and task.artifacts:
                                for artifact in task.artifacts:
                                    if hasattr(artifact, "parts") and artifact.parts:
                                        for p in artifact.parts:
                                            res_text = ""
                                            if hasattr(p, "root") and isinstance(p.root, TextPart):
                                                res_text = p.root.text
                                            elif isinstance(p, TextPart):
                                                res_text = p.text
                                            if isinstance(res_text, str) and res_text:
                                                full_res_text += res_text
                        else:
                            status = getattr(update, "status", None)
                            if status and getattr(status, "message", None):
                                msg = getattr(status, "message", None)
                    elif isinstance(event, A2AMessage):
                        msg = event

                    if msg and msg.parts:
                        for p in msg.parts:
                            # Part is a RootModel[TextPart | FilePart | DataPart]
                            # Extract text from the root discriminated union.
                            res_text = ""
                            if hasattr(p, "root") and isinstance(p.root, TextPart):
                                res_text = p.root.text
                            elif isinstance(p, TextPart):
                                res_text = p.text

                            if isinstance(res_text, str) and res_text:
                                full_res_text += res_text

                if full_res_text:
                    return full_res_text

                logger.warning("A2A_CALL: No response text found from %s", agent_name)
                return None

            except Exception as e:
                attempt += 1
                last_error = e
                logger.warning(f"A2A_CALL_RETRY: Attempt {attempt} failed for {agent_name}: {e}")
                if attempt <= retries:
                    wait_time = backoff**attempt
                    await asyncio.sleep(wait_time)
                else:
                    break

        logger.error(f"A2A_CALL_FAILED: All {retries} attempts failed for {agent_name}: {last_error}")
        if last_error:
            raise last_error
        raise RuntimeError(f"A2A_CALL_FAILED: All {retries} attempts failed for {agent_name}")

    async def close(self):
        """Best-effort cleanup of cached RemoteA2aAgent instances.

        Note: RemoteA2aAgent does not currently expose a cleanup/close method,
        so this only clears the local cache. The underlying httpx connections
        managed by RemoteA2aAgent will be garbage-collected.
        """
        for agent in self._agents.values():
            try:
                if hasattr(agent, "cleanup"):
                    await agent.cleanup()
            except Exception:
                pass
        self._agents.clear()


async def call_agent(
    agent_name: str, message: str, tool_context: ToolContext, session_id: Optional[str] = None
) -> dict:
    """Proactively send a message or instruction to another agent via A2A.

    This is a standardized tool intended to be imported by ANY agent in the simulation.

    Args:
        agent_name: The name of the target agent (e.g., 'runner').
        message: The instruction or query to send.
        tool_context: ADK tool context for A2A client access.
        session_id: Optional explicit session ID for the target agent. If not
            provided, a fresh UUID is generated per call to avoid session reuse
            between caller and callee.
    """
    logger.info(f"A2A_CALL: Agent calling {agent_name} with: {message}")

    # Access the shared client via the plugin's registry
    from agents.utils.communication_plugin import get_client

    iid = tool_context.invocation_id
    a2a_client = get_client(iid)

    try:
        # On AE, tool_context.session.id is the Vertex AI-generated session ID
        # which differs from the gateway's spawn session UUID.  Map back to the
        # original context_id so the frontend's session-based filters match.
        from agents.utils.simulation_registry import get_context_id

        origin_session = str(tool_context.session.id)
        mapped = await get_context_id(origin_session)
        if mapped:
            origin_session = mapped

        simulation_id = tool_context.state.get("simulation_id")

        # Emit a pulse to show inter-agent communication (Request)
        await emit_inter_agent_pulse(
            session_id=origin_session,
            from_agent=tool_context.agent_name,
            to_agent=agent_name,
            message=message,
            simulation_id=simulation_id,
        )

        # Use explicit session_id if provided, otherwise generate a fresh UUID
        # to isolate the callee's session from the caller's.
        from uuid import uuid4

        target_session_id = session_id or str(uuid4())
        response = await a2a_client.call_agent(agent_name, message, session_id=target_session_id)

        # Emit a pulse for the response
        resp_prefix = str(response)[:100] + ("..." if len(str(response)) > 100 else "")
        await emit_inter_agent_pulse(
            session_id=origin_session,
            from_agent=tool_context.agent_name,
            to_agent=agent_name,
            message=resp_prefix,
            direction="response",
            simulation_id=simulation_id,
        )
        return {"status": "success", "agent": agent_name, "response": response}
    except Exception as e:
        logger.error(f"A2A_CALL_ERROR: Failed to call {agent_name}: {e}")
        return {"status": "error", "message": str(e)}
