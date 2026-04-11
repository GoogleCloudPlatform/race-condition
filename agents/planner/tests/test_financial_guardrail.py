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

"""Unit tests for the financial guardrail callback."""

import pytest
from unittest.mock import MagicMock

from google.genai import types

from agents.planner.callbacks import financial_guardrail_callback


@pytest.fixture
def mock_callback_context():
    """Create a mock CallbackContext with controllable state."""
    ctx = MagicMock()
    ctx.state = {}
    return ctx


def _make_request(text: str):
    """Helper to build an LLM request with a single user message."""
    req = MagicMock()
    content = types.Content(
        role="user",
        parts=[types.Part(text=text)],
    )
    req.contents = [content]
    return req


@pytest.fixture
def llm_request_financial_read():
    """LLM request reading financial info (no write intent)."""
    return _make_request("What is the current budget breakdown?")


@pytest.fixture
def llm_request_financial_write():
    """LLM request attempting to change budget."""
    return _make_request("Increase the catering budget by 20%")


@pytest.fixture
def llm_request_planning():
    """LLM request containing a planning question."""
    return _make_request("Plan a marathon in Las Vegas for 5000 runners")


class TestFinancialGuardrail:
    """Tests for the before_model_callback financial guardrail."""

    def test_secure_mode_read_query_passes_through(
        self,
        mock_callback_context,
        llm_request_financial_read,
    ):
        """Financial read queries should pass through even in secure mode."""
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_financial_read,
        )
        assert result is None

    def test_secure_mode_write_query_returns_refusal(
        self,
        mock_callback_context,
        llm_request_financial_write,
    ):
        """Budget change requests should be blocked in secure mode."""
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_financial_write,
        )
        assert result is not None
        assert result.content is not None
        assert result.content.parts is not None
        part_text = result.content.parts[0].text
        assert part_text is not None

    def test_secure_mode_refusal_mentions_change(
        self,
        mock_callback_context,
        llm_request_financial_write,
    ):
        """Refusal text should reference budget changes, not sharing info."""
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_financial_write,
        )
        assert result is not None
        assert result.content is not None
        assert result.content.parts is not None
        part_text = result.content.parts[0].text
        assert part_text is not None
        text = part_text.lower()
        assert any(kw in text for kw in ["change", "modify"])
        assert "share" not in text

    def test_secure_mode_planning_query_passes_through(
        self,
        mock_callback_context,
        llm_request_planning,
    ):
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_planning,
        )
        assert result is None

    def test_insecure_mode_write_query_passes_through(
        self,
        mock_callback_context,
        llm_request_financial_write,
    ):
        """Even write queries pass through in insecure mode."""
        mock_callback_context.state = {"financial_modeling_mode": "insecure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_financial_write,
        )
        assert result is None

    def test_missing_mode_defaults_to_insecure(
        self,
        mock_callback_context,
        llm_request_financial_write,
    ):
        mock_callback_context.state = {}
        result = financial_guardrail_callback(
            mock_callback_context,
            llm_request_financial_write,
        )
        assert result is None

    @pytest.mark.parametrize(
        "text",
        [
            "Change the venue budget allocation",
            "Lower the cost for security",
            "Can you adjust the spending on logistics?",
            "Approve a 10% increase to the fund",
            "Cut the marketing expenses by half",
        ],
    )
    def test_secure_mode_various_write_intents_blocked(
        self,
        mock_callback_context,
        text,
    ):
        """Various write-intent phrasings should trigger the guardrail."""
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            _make_request(text),
        )
        assert result is not None, f"Expected refusal for: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "What is the revenue forecast?",
            "Show me the cost breakdown",
            "How much profit did we make?",
        ],
    )
    def test_secure_mode_various_read_queries_pass(
        self,
        mock_callback_context,
        text,
    ):
        """Read-only financial queries should pass through in secure mode."""
        mock_callback_context.state = {"financial_modeling_mode": "secure"}
        result = financial_guardrail_callback(
            mock_callback_context,
            _make_request(text),
        )
        assert result is None, f"Expected pass-through for: {text!r}"
