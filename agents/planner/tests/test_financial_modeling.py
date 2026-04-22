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

"""Tests for the financial modeling toggle tool and skill loading."""

import pytest
from unittest.mock import MagicMock

from agents.planner.adk_tools import get_tools, set_financial_modeling_mode


class TestSetFinancialModelingMode:
    @pytest.fixture
    def mock_tool_context(self):
        ctx = MagicMock()
        ctx.state = {}
        return ctx

    @pytest.mark.asyncio
    async def test_set_insecure_mode(self, mock_tool_context):
        result = await set_financial_modeling_mode(mode="insecure", tool_context=mock_tool_context)
        assert result == {
            "status": "success",
            "financial_modeling_mode": "insecure",
        }
        assert mock_tool_context.state["financial_modeling_mode"] == "insecure"

    @pytest.mark.asyncio
    async def test_set_secure_mode(self, mock_tool_context):
        result = await set_financial_modeling_mode(mode="secure", tool_context=mock_tool_context)
        assert result == {
            "status": "success",
            "financial_modeling_mode": "secure",
        }
        assert mock_tool_context.state["financial_modeling_mode"] == "secure"

    @pytest.mark.asyncio
    async def test_invalid_mode_returns_error(self, mock_tool_context):
        result = await set_financial_modeling_mode(mode="invalid", tool_context=mock_tool_context)
        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()
        assert "financial_modeling_mode" not in mock_tool_context.state

    @pytest.mark.asyncio
    async def test_toggle_overwrites_previous_mode(self, mock_tool_context):
        await set_financial_modeling_mode(mode="secure", tool_context=mock_tool_context)
        assert mock_tool_context.state["financial_modeling_mode"] == "secure"
        await set_financial_modeling_mode(mode="insecure", tool_context=mock_tool_context)
        assert mock_tool_context.state["financial_modeling_mode"] == "insecure"


class TestFinancialModelingSkillLoading:
    def test_financial_modeling_skills_are_loaded(self):
        tools = get_tools()
        from google.adk.tools.skill_toolset import SkillToolset

        skill_toolsets = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(skill_toolsets) == 1
        skills = skill_toolsets[0]._skills
        # Skills may be stored as strings (names) or objects with .name
        skill_names = [s if isinstance(s, str) else s.name for s in skills]
        assert "insecure-financial-modeling" in skill_names
        assert "secure-financial-modeling" in skill_names

    def test_toggle_tool_is_in_tools_list(self):
        tools = get_tools()
        from google.adk.tools.function_tool import FunctionTool

        func_tools = [t for t in tools if isinstance(t, FunctionTool)]
        func_names = [t.func.__name__ for t in func_tools]
        assert "set_financial_modeling_mode" in func_names
