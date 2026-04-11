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

"""Tests asserting evaluate_plan persists its result to session state.

Per the state-driven memory persistence design (docs/plans/2026-04-19-...),
downstream tools (store_route) read evaluation_result from session state
rather than receiving it as an LLM-supplied JSON string.  Therefore
evaluate_plan MUST write its returned dict to tool_context.state on every
return path.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.planner_with_eval.evaluator.tools import evaluate_plan


def _make_tool_context() -> MagicMock:
    ctx = MagicMock()
    ctx.state = {}
    return ctx


@pytest.mark.asyncio
async def test_evaluate_plan_writes_result_to_state_on_heuristic_path(monkeypatch):
    """Heuristic eval path (no project_id) MUST write evaluation_result to state."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    ctx = _make_tool_context()
    request = json.dumps({"user_intent": "test", "proposed_plan": "test plan"})

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=([], "ok")),
    ):
        result = await evaluate_plan(request, tool_context=ctx)

    assert "evaluation_result" in ctx.state, "evaluate_plan did not write evaluation_result to state"
    assert ctx.state["evaluation_result"] == result
    assert isinstance(ctx.state["evaluation_result"], dict)


@pytest.mark.asyncio
async def test_evaluate_plan_writes_result_to_state_on_parse_error():
    """Parse-error early-return path MUST also write evaluation_result to state."""
    ctx = _make_tool_context()

    result = await evaluate_plan("not valid json", tool_context=ctx)

    assert result["eval_method"] == "error"
    assert "evaluation_result" in ctx.state, "evaluate_plan did not write evaluation_result on parse error"
    assert ctx.state["evaluation_result"] == result


@pytest.mark.asyncio
async def test_evaluate_plan_writes_result_to_state_on_vertex_path(monkeypatch):
    """Vertex AI eval path MUST write evaluation_result to state."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    ctx = _make_tool_context()
    request = json.dumps({"user_intent": "test", "proposed_plan": "test plan"})

    fake_scores = {
        "safety_compliance": 80,
        "logistics_completeness": 80,
        "participant_experience": 80,
        "community_impact": 80,
        "financial_viability": 80,
        "intent_alignment": 80,
        "distance_compliance": 100,
    }
    fake_details = {k: "stub" for k in fake_scores}

    with (
        patch(
            "agents.planner_with_eval.evaluator.tools._run_custom_eval",
            new=AsyncMock(return_value=(fake_scores, fake_details)),
        ),
        patch(
            "agents.planner_with_eval.evaluator.tools._generate_feedback",
            new=AsyncMock(return_value=([], "ok")),
        ),
    ):
        result = await evaluate_plan(request, tool_context=ctx)

    assert ctx.state.get("evaluation_result") == result
    assert ctx.state["evaluation_result"]["eval_method"] == "vertex_ai_eval"


@pytest.mark.asyncio
async def test_evaluate_plan_does_not_crash_when_tool_context_missing(monkeypatch):
    """Calling without tool_context (legacy) MUST NOT crash; just skip the state write."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    request = json.dumps({"user_intent": "test", "proposed_plan": "test plan"})

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=([], "ok")),
    ):
        result = await evaluate_plan(request, tool_context=None)

    assert isinstance(result, dict)
    assert "eval_method" in result
