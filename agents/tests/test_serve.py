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

"""Tests for agents.utils.serve — unified agent serving abstraction."""

from unittest.mock import MagicMock, patch, ANY
from fastapi import FastAPI


def _make_mock_fast_api_app():
    return FastAPI()


class TestCreateAgentApp:
    """Tests for create_agent_app() — verifies CORS and A2A wiring."""

    @patch("agents.utils.serve._register_a2a")
    @patch("agents.utils.serve.get_fast_api_app", return_value=_make_mock_fast_api_app())
    def test_calls_get_fast_api_app_with_correct_args(self, mock_get_app, mock_reg_a2a):
        from agents.utils.serve import create_agent_app

        create_agent_app(
            name="test",
            agents_dir="agents/test",
            adk_app=MagicMock(),
            agent_card=MagicMock(),
        )
        mock_get_app.assert_called_once_with(agents_dir="agents/test", a2a=False, web=False)

    @patch("agents.utils.serve._register_a2a")
    @patch("agents.utils.serve.get_fast_api_app", return_value=_make_mock_fast_api_app())
    def test_registers_a2a_routes(self, mock_get_app, mock_reg_a2a):
        from agents.utils.serve import create_agent_app

        adk_app = MagicMock()
        agent_card = MagicMock()
        create_agent_app(
            name="test",
            agents_dir="agents/test",
            adk_app=adk_app,
            agent_card=agent_card,
        )
        mock_reg_a2a.assert_called_once_with(ANY, adk_app, agent_card, "test", None)

    @patch("agents.utils.serve._register_a2a")
    @patch("agents.utils.serve.get_fast_api_app", return_value=_make_mock_fast_api_app())
    def test_adds_cors_middleware(self, mock_get_app, mock_reg_a2a):
        from fastapi.testclient import TestClient
        from agents.utils.serve import create_agent_app

        app = create_agent_app(
            name="test",
            agents_dir="agents/test",
            adk_app=MagicMock(),
            agent_card=MagicMock(),
        )
        client = TestClient(app)
        response = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" in response.headers

    @patch("agents.utils.serve._register_a2a")
    @patch("agents.utils.serve.get_fast_api_app", return_value=_make_mock_fast_api_app())
    def test_cors_reads_from_env_var(self, mock_get_app, mock_reg_a2a):
        import os
        from fastapi.testclient import TestClient
        from agents.utils.serve import create_agent_app

        os.environ["CORS_ALLOWED_ORIGINS"] = "https://example.com"
        try:
            app = create_agent_app(
                name="test",
                agents_dir="agents/test",
                adk_app=MagicMock(),
                agent_card=MagicMock(),
            )
            client = TestClient(app)
            response = client.options(
                "/",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.headers.get("access-control-allow-origin") == "https://example.com"
        finally:
            del os.environ["CORS_ALLOWED_ORIGINS"]


class TestServeAgent:
    @patch("agents.utils.serve.uvicorn")
    def test_uvicorn_config(self, mock_uvicorn):
        from agents.utils.serve import serve_agent

        app = MagicMock()
        serve_agent(app, port=8000)
        mock_uvicorn.run.assert_called_once()
        kwargs = mock_uvicorn.run.call_args.kwargs
        assert kwargs["proxy_headers"] is True
        assert kwargs["forwarded_allow_ips"] == "*"
