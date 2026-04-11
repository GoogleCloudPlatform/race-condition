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

import time
import pytest
import httpx
import respx
from httpx import Response
from agents.utils.communication import SimulationA2AClient, call_agent
from a2a.types import AgentCard, TransportProtocol, Message as A2AMessage, Part, TextPart, Role
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def a2a_client():
    return SimulationA2AClient(gateway_url="http://gateway:8101")


@respx.mock
@pytest.mark.asyncio
async def test_registry_discovery(a2a_client):
    """Verify that the client correctly fetches and parses agent types from the Gateway."""
    mock_data = {
        "runner_autopilot": {
            "name": "runner_autopilot",
            "url": "http://runner_autopilot:8210",
            "preferred_transport": "HTTP+JSON",
            "description": "Mock runner_autopilot",
            "version": "1.0.0",
            "capabilities": {"streaming": True},
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [],
        }
    }
    respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json=mock_data))

    cards = await a2a_client._discover_agents()
    assert "runner_autopilot" in cards
    assert cards["runner_autopilot"].url == "http://runner_autopilot:8210"
    assert cards["runner_autopilot"].preferred_transport == TransportProtocol.http_json


@respx.mock
@pytest.mark.asyncio
async def test_registry_card_transport_normalized_to_jsonrpc(a2a_client):
    """Cards from registry must be normalized to jsonrpc since all servers speak JSON-RPC."""
    mock_data = {
        "simulator": {
            "name": "simulator",
            "url": "http://simulator:8202/a2a/simulator/",
            "preferred_transport": "HTTP+JSON",
            "description": "Mock simulator",
            "version": "1.0.0",
            "capabilities": {"streaming": False},
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [],
        }
    }
    respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json=mock_data))

    agent = await a2a_client.get_agent("simulator")
    # The card on the agent must be jsonrpc, not http_json
    assert agent._agent_card.preferred_transport == TransportProtocol.jsonrpc


@pytest.mark.asyncio
async def test_get_agent_fallback_env(a2a_client, monkeypatch):
    """Verify fallback to environment variables if registry discovery fails or is empty."""
    # Mock empty registry
    a2a_client._discover_agents = AsyncMock(return_value={})

    monkeypatch.setenv("HELPER_URL", "http://helper:8205")

    agent = await a2a_client.get_agent("helper")
    assert agent.name == "helper"
    assert agent._agent_card.url == "http://helper:8205/a2a/helper/"


@pytest.mark.asyncio
async def test_call_agent_success(a2a_client):
    """Verify successful A2A call flow with response parsing."""
    mock_agent = MagicMock()
    mock_agent._ensure_resolved = AsyncMock()

    # Mock the internal A2A client and its send_message generator
    mock_a2a_client = MagicMock()

    async def mock_send_message(*args, **kwargs):
        # Yield an A2A message with a part
        # Message requires message_id, parts, role
        yield A2AMessage(
            message_id="resp-1",
            parts=[Part(root=TextPart(text="Vitals: OK"))],
            role=Role.agent,
        )

    mock_a2a_client.send_message = mock_send_message
    mock_agent._a2a_client = mock_a2a_client

    a2a_client.get_agent = AsyncMock(return_value=mock_agent)

    response = await a2a_client.call_agent("runner_autopilot", "get_vitals")
    assert response == "Vitals: OK"
    a2a_client.get_agent.assert_called_with("runner_autopilot")


@pytest.mark.asyncio
async def test_call_agent_retry_resilience(a2a_client):
    """Verify that the client retries on failures (e.g., cold starts)."""
    mock_agent = MagicMock()
    mock_agent._ensure_resolved = AsyncMock()

    # Mock a failing then succeeding call
    calls = []

    async def mock_send_message_fail_then_succeed(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise Exception("Gateway Timeout (Cold Start)")

        yield A2AMessage(
            message_id="resp-2",
            parts=[Part(root=TextPart(text="Recovered"))],
            role=Role.agent,
        )

    mock_a2a_client = MagicMock()
    mock_a2a_client.send_message = mock_send_message_fail_then_succeed
    mock_agent._a2a_client = mock_a2a_client

    a2a_client.get_agent = AsyncMock(return_value=mock_agent)

    # Use small delay for test speed
    response = await a2a_client.call_agent("runner_autopilot", "status", retries=2, backoff=0.01)

    assert response == "Recovered"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fallback_card_uses_jsonrpc_transport(a2a_client, monkeypatch):
    """Fallback AgentCards must use jsonrpc to match ADK's default ClientFactory."""
    a2a_client._discover_agents = AsyncMock(return_value={})
    monkeypatch.setenv("SIMULATOR_URL", "http://simulator:8202")

    agent = await a2a_client.get_agent("simulator")
    assert agent._agent_card.preferred_transport == TransportProtocol.jsonrpc


@pytest.mark.asyncio
async def test_remote_agent_receives_dual_transport_factory(a2a_client, monkeypatch):
    """RemoteA2aAgent must be created with a ClientFactory that supports both jsonrpc and http_json."""
    a2a_client._discover_agents = AsyncMock(return_value={})
    monkeypatch.setenv("SIMULATOR_URL", "http://simulator:8202")

    agent = await a2a_client.get_agent("simulator")
    # The RemoteA2aAgent should have a factory that has both transports registered
    factory = agent._a2a_client_factory
    assert factory is not None
    assert TransportProtocol.jsonrpc in factory._registry
    assert TransportProtocol.http_json in factory._registry


def test_simulator_agent_card_uses_http_json():
    """Simulator agent card uses http_json as mandated by Vertex AI SDK."""
    import agents.simulator.agent as sim_module

    card = sim_module.agent_card
    assert card.preferred_transport == TransportProtocol.http_json


@pytest.mark.asyncio
async def test_client_factory_handles_http_json_server(a2a_client, monkeypatch):
    """Client factory must support http_json servers even though fallback cards use jsonrpc."""
    a2a_client._discover_agents = AsyncMock(return_value={})
    monkeypatch.setenv("SIMULATOR_URL", "http://simulator:8202")

    agent = await a2a_client.get_agent("simulator")
    factory = agent._a2a_client_factory

    # Simulate what happens when server advertises http_json (like the simulator)
    from a2a.types import AgentCard as TestCard, AgentCapabilities as TestCaps

    http_json_card = TestCard(
        name="simulator",
        url="http://simulator:8202",
        description="test",
        version="1.0.0",
        capabilities=TestCaps(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
        preferred_transport=TransportProtocol.http_json,
    )
    # This must NOT raise "no compatible transports found"
    client = factory.create(http_json_card)
    assert client is not None


@pytest.mark.asyncio
async def test_get_agent_fallback_env_includes_a2a_path(a2a_client, monkeypatch):
    """Fallback cards from env vars must include the /a2a/{name}/ path."""
    a2a_client._discover_agents = AsyncMock(return_value={})
    monkeypatch.setenv("SIMULATOR_URL", "http://simulator:8202")

    agent = await a2a_client.get_agent("simulator")
    assert agent._agent_card.url == "http://simulator:8202/a2a/simulator/"


def test_gateway_url_prefers_internal(monkeypatch):
    """SimulationA2AClient should prefer GATEWAY_INTERNAL_URL over GATEWAY_URL."""
    monkeypatch.setenv("GATEWAY_INTERNAL_URL", "https://gateway-internal.run.app")
    monkeypatch.setenv("GATEWAY_URL", "https://gateway.public.example.com")

    client = SimulationA2AClient()
    assert client.gateway_url == "https://gateway-internal.run.app"


def test_gateway_url_falls_back_to_public(monkeypatch):
    """When GATEWAY_INTERNAL_URL is not set, use GATEWAY_URL."""
    monkeypatch.delenv("GATEWAY_INTERNAL_URL", raising=False)
    monkeypatch.setenv("GATEWAY_URL", "https://gateway.public.example.com")

    client = SimulationA2AClient()
    assert client.gateway_url == "https://gateway.public.example.com"


@pytest.mark.asyncio
async def test_get_agent_fallback_checks_internal_url(a2a_client, monkeypatch):
    """Fallback should check {NAME}_INTERNAL_URL when {NAME}_URL is not set."""
    a2a_client._discover_agents = AsyncMock(return_value={})
    monkeypatch.delenv("SIMULATOR_URL", raising=False)
    monkeypatch.setenv(
        "SIMULATOR_INTERNAL_URL",
        "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456",
    )

    agent = await a2a_client.get_agent("simulator")
    # AE internal URLs should be used directly (no /a2a/{name}/ appended)
    assert "reasoningEngines" in agent._agent_card.url


@pytest.mark.asyncio
async def test_ae_card_keeps_http_json_transport(a2a_client):
    """AE agent cards should keep http_json transport, not be forced to jsonrpc."""
    ae_url = (
        "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456"
    )
    mock_data = {
        "simulator": {
            "name": "simulator",
            "url": ae_url,
            "preferred_transport": "HTTP+JSON",
            "description": "AE simulator",
            "version": "1.0.0",
            "capabilities": {},
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [],
        }
    }
    a2a_client._discover_agents = AsyncMock(
        return_value={name: AgentCard.model_validate(data) for name, data in mock_data.items()}
    )

    agent = await a2a_client.get_agent("simulator")
    # AE cards should NOT be forced to jsonrpc
    assert agent._agent_card.preferred_transport == TransportProtocol.http_json


@pytest.mark.asyncio
async def test_call_agent_default_generates_fresh_session_id():
    """call_agent must generate a fresh UUID context_id, NOT reuse caller's session.id."""
    from uuid import UUID

    mock_session = MagicMock()
    mock_session.id = "caller-session-999"

    mock_tool_context = MagicMock()
    mock_tool_context.session = mock_session
    mock_tool_context.invocation_id = "test-iid"
    mock_tool_context.agent_name = "orchestrator"

    # Capture the A2AMessage sent to the remote agent
    captured_messages = []

    async def mock_send_message(msg):
        captured_messages.append(msg)
        from a2a.types import Message as A2AMsg, Part as P, TextPart as TP, Role as R

        yield A2AMsg(
            message_id="resp-1",
            parts=[P(root=TP(text="ok"))],
            role=R.agent,
        )

    mock_remote_agent = MagicMock()
    mock_remote_agent._a2a_client.send_message = mock_send_message
    mock_remote_agent._ensure_resolved = AsyncMock()

    real_client = SimulationA2AClient()
    real_client._registry_cache = {"runner_autopilot": MagicMock()}
    with (
        patch.object(real_client, "_discover_agents", new_callable=AsyncMock) as mock_discover,
        patch("agents.utils.communication_plugin.get_client", return_value=real_client),
        patch("agents.utils.communication.RemoteA2aAgent", return_value=mock_remote_agent),
        patch("agents.utils.communication.emit_inter_agent_pulse", new_callable=AsyncMock),
    ):
        mock_discover.return_value = real_client._registry_cache

        result = await call_agent("runner_autopilot", "hello", mock_tool_context)

        assert result["status"] == "success"
        assert len(captured_messages) == 1

        a2a_msg = captured_messages[0]
        # context_id must NOT be the caller's session id
        assert a2a_msg.context_id != "caller-session-999"
        # context_id must be a valid UUID
        UUID(a2a_msg.context_id)  # Raises ValueError if not valid UUID


@pytest.mark.asyncio
async def test_call_agent_explicit_session_id_passed_through():
    """call_agent with explicit session_id must use it as context_id."""
    mock_session = MagicMock()
    mock_session.id = "caller-session-999"

    mock_tool_context = MagicMock()
    mock_tool_context.session = mock_session
    mock_tool_context.invocation_id = "test-iid"
    mock_tool_context.agent_name = "orchestrator"

    captured_messages = []

    async def mock_send_message(msg):
        captured_messages.append(msg)
        from a2a.types import Message as A2AMsg, Part as P, TextPart as TP, Role as R

        yield A2AMsg(
            message_id="resp-1",
            parts=[P(root=TP(text="ok"))],
            role=R.agent,
        )

    mock_remote_agent = MagicMock()
    mock_remote_agent._a2a_client.send_message = mock_send_message
    mock_remote_agent._ensure_resolved = AsyncMock()

    real_client = SimulationA2AClient()
    real_client._registry_cache = {"runner_autopilot": MagicMock()}
    with (
        patch.object(real_client, "_discover_agents", new_callable=AsyncMock) as mock_discover,
        patch("agents.utils.communication_plugin.get_client", return_value=real_client),
        patch("agents.utils.communication.RemoteA2aAgent", return_value=mock_remote_agent),
        patch("agents.utils.communication.emit_inter_agent_pulse", new_callable=AsyncMock),
    ):
        mock_discover.return_value = real_client._registry_cache

        result = await call_agent("runner_autopilot", "hello", mock_tool_context, session_id="explicit-session-123")

        assert result["status"] == "success"
        assert len(captured_messages) == 1

        a2a_msg = captured_messages[0]
        assert a2a_msg.context_id == "explicit-session-123"


class TestDiscoveryCache:
    """Verify module-level discovery cache behavior."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_discovery_cache_prevents_second_http_call(self, a2a_client):
        """Second call within TTL should not make HTTP request."""
        from agents.utils import communication

        # Reset cache
        communication._discovery_cache = {}
        communication._discovery_cache_ts = 0.0

        route = respx.get("http://gateway:8101/api/v1/agent-types").mock(
            return_value=httpx.Response(
                200,
                json={
                    "simulator": {
                        "name": "simulator",
                        "url": "http://simulator:8202",
                        "description": "Mock simulator",
                        "version": "1.0.0",
                        "capabilities": {},
                        "skills": [],
                        "default_input_modes": ["text/plain"],
                        "default_output_modes": ["text/plain"],
                    }
                },
            )
        )

        # First call should hit network
        await a2a_client._discover_agents()
        assert route.call_count == 1

        # Second call should use cache
        await a2a_client._discover_agents()
        assert route.call_count == 1  # Still 1 — cache hit

    @respx.mock
    @pytest.mark.asyncio
    async def test_discovery_cache_expires_after_ttl(self, a2a_client):
        """Cache should expire and re-fetch after TTL."""
        from agents.utils import communication

        communication._discovery_cache = {}
        communication._discovery_cache_ts = 0.0

        route = respx.get("http://gateway:8101/api/v1/agent-types").mock(
            return_value=httpx.Response(
                200,
                json={
                    "simulator": {
                        "name": "simulator",
                        "url": "http://simulator:8202",
                        "description": "Mock simulator",
                        "version": "1.0.0",
                        "capabilities": {},
                        "skills": [],
                        "default_input_modes": ["text/plain"],
                        "default_output_modes": ["text/plain"],
                    }
                },
            )
        )

        await a2a_client._discover_agents()
        assert route.call_count == 1

        # Simulate TTL expiry
        communication._discovery_cache_ts = time.monotonic() - 31.0
        await a2a_client._discover_agents()
        assert route.call_count == 2  # Re-fetched


class TestClientCleanup:
    """Verify clients are properly closed."""

    @pytest.mark.asyncio
    async def test_close_cleans_up_agents(self):
        """close() should clear the agents dict."""
        client = SimulationA2AClient(gateway_url="http://gateway:8101")
        # Manually add a mock agent
        mock_agent = MagicMock()
        mock_agent.cleanup = AsyncMock()
        client._agents["test"] = mock_agent

        await client.close()
        assert len(client._agents) == 0
        mock_agent.cleanup.assert_awaited_once()


@pytest.fixture(autouse=True)
def _reset_discovery_cache():
    """Reset the module-level discovery cache and shared client between tests."""
    from agents.utils import communication

    communication._discovery_cache = {}
    communication._discovery_cache_ts = 0.0
    communication._discovery_client = None
    yield
    communication._discovery_cache = {}
    communication._discovery_cache_ts = 0.0
    communication._discovery_client = None


@pytest.fixture(autouse=True)
def mock_genai():
    # Patch the genai Client itself to be safe for all A2A tests
    with patch("google.genai.Client") as m:
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock()
        mock_client.aio.models.generate_content_stream = AsyncMock()
        m.return_value = mock_client
        yield m


# =====================================================================
# OIDC auth (Cloud Run service-to-service)
# =====================================================================


class TestOIDCAuth:
    """Tests for the _OIDCAuth httpx auth handler."""

    def test_attaches_bearer_token_when_audience_resolves(self):
        """When get_id_token returns a token, auth_flow sets Authorization header."""
        from agents.utils.communication import _OIDCAuth

        auth_handler = _OIDCAuth(audience="https://gateway.run.app")
        request = httpx.Request("GET", "https://gateway.run.app/api/v1/agent-types")

        with patch("agents.utils.auth.get_id_token", return_value="eyJfaketoken"):
            # Drive the auth flow generator like httpx does.
            flow = auth_handler.auth_flow(request)
            authed_request = next(flow)

        assert authed_request.headers["Authorization"] == "Bearer eyJfaketoken"

    def test_no_header_when_token_unavailable(self):
        """When get_id_token returns None (no audience / ADC failure), no header is set."""
        from agents.utils.communication import _OIDCAuth

        auth_handler = _OIDCAuth(audience="")  # empty audience -> get_id_token returns None
        request = httpx.Request("GET", "https://gateway.run.app/health")

        with patch("agents.utils.auth.get_id_token", return_value=None):
            flow = auth_handler.auth_flow(request)
            authed_request = next(flow)

        assert "Authorization" not in authed_request.headers


class TestNonAEAgentUsesOIDCAuth:
    """Regression: non-AE (Cloud Run / local) agents must use _OIDCAuth, not None."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_agent_for_cloudrun_card_constructs_client_with_oidc_auth(self, a2a_client, monkeypatch):
        """When the resolved card URL is non-AE, the per-agent httpx client uses _OIDCAuth."""
        from agents.utils.communication import _OIDCAuth

        monkeypatch.setenv("PLANNER_URL", "https://planner-cloudrun.run.app")
        respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json={}))

        captured_auth = []
        original_async_client = httpx.AsyncClient

        def capture_async_client(*args, **kwargs):
            captured_auth.append(kwargs.get("auth"))
            return original_async_client(*args, **kwargs)

        with patch("agents.utils.communication.httpx.AsyncClient", side_effect=capture_async_client):
            await a2a_client.get_agent("planner")

        assert any(isinstance(a, _OIDCAuth) for a in captured_auth), (
            f"Expected at least one httpx.AsyncClient with _OIDCAuth; got {captured_auth!r}"
        )


class TestDiscoveryAttachesOIDC:
    """Discovery call to gateway must attach OIDC token in OSS mode."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_discovery_attaches_authorization_when_token_resolves(self, a2a_client, monkeypatch):
        """When get_id_token returns a token, discovery sends Authorization: Bearer."""
        route = respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json={}))

        with patch("agents.utils.auth.get_id_token", return_value="eyJfaketoken"):
            await a2a_client._discover_agents()

        assert route.called
        assert route.calls.last.request.headers.get("Authorization") == "Bearer eyJfaketoken"

    @respx.mock
    @pytest.mark.asyncio
    async def test_discovery_omits_authorization_when_token_unavailable(self, a2a_client, monkeypatch):
        """When get_id_token returns None (local dev / no ADC), discovery still works."""
        route = respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json={}))

        with patch("agents.utils.auth.get_id_token", return_value=None):
            await a2a_client._discover_agents()

        assert route.called
        assert "Authorization" not in route.calls.last.request.headers


class TestAEAgentKeepsGCPAuth:
    """Regression: AE agents must continue to use _GCPAuth (OAuth2 cloud-platform)."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_agent_for_ae_card_constructs_client_with_gcpauth(self, a2a_client, monkeypatch):
        """AE URLs trigger _GCPAuth (OAuth2), not _OIDCAuth, since AE accepts cloud-platform tokens."""
        from agents.utils.communication import _GCPAuth

        monkeypatch.setenv(
            "SIMULATOR_URL",
            "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/reasoningEngines/123",
        )
        respx.get("http://gateway:8101/api/v1/agent-types").mock(return_value=Response(200, json={}))

        captured_auth = []
        original_async_client = httpx.AsyncClient

        def capture_async_client(*args, **kwargs):
            captured_auth.append(kwargs.get("auth"))
            return original_async_client(*args, **kwargs)

        with patch.object(_GCPAuth, "__init__", lambda self: None):  # skip ADC
            with patch("agents.utils.communication.httpx.AsyncClient", side_effect=capture_async_client):
                await a2a_client.get_agent("simulator")

        assert any(isinstance(a, _GCPAuth) for a in captured_auth), (
            f"Expected at least one httpx.AsyncClient with _GCPAuth; got {captured_auth!r}"
        )
