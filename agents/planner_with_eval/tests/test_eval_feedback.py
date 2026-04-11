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

"""Tests for the evaluate_plan FunctionTool and LLM feedback generation."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from agents.planner_with_eval.evaluator.config import (
    CRITERION_WEIGHTS,
    EVALUATION_CRITERIA,
    PASS_THRESHOLD,
)


def test_pass_threshold_in_config():
    """PASS_THRESHOLD must be defined in config.py and set to 75."""
    assert PASS_THRESHOLD == 75


def test_evaluation_criteria_in_config():
    """EVALUATION_CRITERIA must list all 7 criteria in order."""
    assert EVALUATION_CRITERIA == [
        "safety_compliance",
        "logistics_completeness",
        "participant_experience",
        "community_impact",
        "financial_viability",
        "intent_alignment",
        "distance_compliance",
    ]


def test_criterion_weights_sum_to_one():
    """Weights must sum to 1.0."""
    assert abs(sum(CRITERION_WEIGHTS.values()) - 1.0) < 1e-9


def test_criterion_weights_has_seven_entries():
    """Expanded model has exactly 7 equally-weighted criteria."""
    expected_keys = {
        "safety_compliance",
        "logistics_completeness",
        "participant_experience",
        "community_impact",
        "financial_viability",
        "intent_alignment",
        "distance_compliance",
    }
    assert set(CRITERION_WEIGHTS.keys()) == expected_keys


def test_criterion_weights_are_equal():
    """All 7 criteria must have equal weight (1/7 each)."""
    expected_weight = 1.0 / 7
    for criterion, weight in CRITERION_WEIGHTS.items():
        assert abs(weight - expected_weight) < 1e-9, f"{criterion} weight {weight} != expected {expected_weight}"


@pytest.mark.asyncio
async def test_generate_feedback_returns_suggestions_and_summary():
    """_generate_feedback makes one GenerateContent call and returns suggestions + summary."""
    from agents.planner_with_eval.evaluator.tools import _generate_feedback

    mock_response = MagicMock()
    mock_response.text = '{"suggestions": ["Add emergency crossings"], "summary": "Plan needs work"}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.planner_with_eval.evaluator.tools.genai") as mock_genai:
        mock_genai.Client.return_value = mock_client

        suggestions, summary = await _generate_feedback(
            scores={"safety_compliance": 60, "logistics_completeness": 80, "distance_compliance": 100},
            details={"safety_compliance": "Safety gaps"},
            user_intent="Plan a marathon in NYC",
            proposed_plan="A 26.2 mile route",
        )

    assert isinstance(suggestions, list)
    assert len(suggestions) > 0
    assert isinstance(summary, str)
    assert len(summary) > 0
    mock_client.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_generate_feedback_graceful_fallback():
    """If GenerateContent fails, _generate_feedback returns deterministic fallback."""
    from agents.planner_with_eval.evaluator.tools import _generate_feedback

    with patch("agents.planner_with_eval.evaluator.tools.genai") as mock_genai:
        mock_genai.Client.side_effect = Exception("API error")

        suggestions, summary = await _generate_feedback(
            scores={"safety_compliance": 60, "logistics_completeness": 80, "distance_compliance": 100},
            details={"safety_compliance": "Safety gaps"},
            user_intent="Plan a marathon",
            proposed_plan="A route",
        )

    assert isinstance(suggestions, list)
    assert isinstance(summary, str)


@pytest.mark.asyncio
async def test_evaluate_plan_includes_llm_suggestions():
    """evaluate_plan result must include LLM-generated suggestions and summary."""
    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=(["LLM suggestion"], "LLM summary")),
    ):
        with patch.dict("os.environ", {}, clear=True):
            result = await evaluate_plan(
                json.dumps(
                    {
                        "user_intent": "Plan a marathon in NYC",
                        "proposed_plan": "A 26.2 mile route through NYC",
                    }
                ),
            )

    assert result["improvement_suggestions"] == ["LLM suggestion"]
    assert result["summary"] == "LLM summary"


@pytest.mark.asyncio
async def test_evaluate_plan_heuristic_returns_seven_criteria():
    """Heuristic fallback must return all 7 criteria."""
    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=(["suggestion"], "summary")),
    ):
        with patch.dict("os.environ", {}, clear=True):
            result = await evaluate_plan(
                json.dumps(
                    {
                        "user_intent": "Plan a marathon in NYC",
                        "proposed_plan": "A 26.2 mile route",
                    }
                ),
            )

    assert result["eval_method"] == "heuristic"
    expected_keys = {
        "safety_compliance",
        "logistics_completeness",
        "participant_experience",
        "community_impact",
        "financial_viability",
        "intent_alignment",
        "distance_compliance",
    }
    assert set(result["scores"].keys()) == expected_keys
    assert "overall_score" in result
    assert "passed" in result


@pytest.mark.asyncio
async def test_evaluate_plan_enriches_context_with_traffic_assessment():
    """evaluate_plan should enrich context with traffic_assessment from session state."""
    from agents.planner_with_eval.evaluator.tools import evaluate_plan, _heuristic_eval

    mock_tool_context = MagicMock()
    mock_tool_context.state = {
        "marathon_route": {"type": "FeatureCollection", "features": []},
        "traffic_assessment": {
            "status": "success",
            "narrative": "Low traffic impact expected",
            "congestion_zones": [{"zone_name": "Strip", "severity": "medium"}],
        },
    }

    # Track what _heuristic_eval receives to verify enrichment
    original_heuristic = _heuristic_eval
    captured_plans = []

    def tracking_heuristic(user_intent, proposed_plan):
        captured_plans.append(proposed_plan)
        return original_heuristic(user_intent, proposed_plan)

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=(["suggestion"], "summary")),
    ):
        with patch(
            "agents.planner_with_eval.evaluator.tools._heuristic_eval",
            side_effect=tracking_heuristic,
        ):
            with patch.dict("os.environ", {}, clear=True):
                result = await evaluate_plan(
                    json.dumps(
                        {
                            "user_intent": "Plan a marathon in Las Vegas",
                            "proposed_plan": "A 26.2 mile route through Las Vegas",
                        }
                    ),
                    tool_context=mock_tool_context,
                )

    assert result["eval_method"] == "heuristic"
    # Verify traffic assessment was injected into the plan context
    assert len(captured_plans) == 1
    assert "Traffic Assessment" in captured_plans[0]
    assert "Low traffic impact expected" in captured_plans[0]


@pytest.mark.asyncio
async def test_heuristic_fallback_passes_for_minimal_clean_plan():
    """A minimal plan with correct distance and no red flags should pass heuristic eval.

    This plan deliberately omits bonus keywords (community, cheer zone, etc.)
    to verify the base heuristic defaults are high enough to pass.
    """
    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=([], "Plan meets all criteria.")),
    ):
        with patch.dict("os.environ", {}, clear=True):
            result = await evaluate_plan(
                json.dumps(
                    {
                        "user_intent": "Plan a marathon in Las Vegas",
                        "proposed_plan": (
                            "A 26.2 mile marathon route through Las Vegas. The route passes through the Strip."
                        ),
                    }
                ),
            )

    assert result["eval_method"] == "heuristic"
    assert result["passed"] is True, (
        f"Minimal clean plan should pass heuristic eval. Scores: {result['scores']}, Overall: {result['overall_score']}"
    )


def test_heuristic_defaults_above_70_per_criterion():
    """Base heuristic defaults should produce each criterion >= 70.

    When no red flags or bonuses trigger, each individual criterion's
    default score should be at least 70 so clean plans reliably
    clear the threshold.
    """
    from agents.planner_with_eval.evaluator.tools import _heuristic_eval

    scores, _ = _heuristic_eval(
        user_intent="Plan a marathon",
        proposed_plan="A 26.2 mile marathon route through the city.",
    )
    non_deterministic = {
        "safety_compliance",
        "logistics_completeness",
        "participant_experience",
        "community_impact",
        "financial_viability",
        "intent_alignment",
    }
    for criterion in non_deterministic:
        assert criterion in scores, f"Missing criterion: {criterion}"
        assert scores[criterion] >= 70, f"Default heuristic {criterion} {scores[criterion]} is below 70"
    assert "distance_compliance" in scores


@pytest.mark.asyncio
async def test_realistic_plan_passes_heuristic_evaluation():
    """A realistic planner-quality plan must pass the heuristic evaluator.

    This test uses a plan text representative of what the planner agent
    actually produces, including safety provisions, community engagement,
    intent alignment, and correct distance. It proves the scoring system
    and planner output are in sync.
    """
    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    realistic_plan = (
        "Las Vegas Marathon Plan - April 2026\n\n"
        "Route: A 26.2 mile marathon route starting at the Las Vegas Sign on "
        "Las Vegas Boulevard, sweeping through residential communities in the "
        "Arts District and Historic Westside, before sweeping through "
        "neighborhoods to finish near Michelob Ultra Arena.\n\n"
        "Safety Provisions:\n"
        "- Emergency vehicle crossing points at miles 5, 10, 15, and 20\n"
        "- Emergency corridor access maintained to University Medical Center, "
        "Las Vegas Fire Station 1, and LVMPD headquarters\n"
        "- Evacuation routes via cross-streets every 2 miles\n"
        "- Crowd safety barriers at high-density spectator zones\n"
        "- Medical tents at halfway point and finish line\n\n"
        "Community Impact:\n"
        "- Resident notification program 30 days before event\n"
        "- Business access corridors maintained on parallel streets\n"
        "- Equitable routing through diverse neighborhoods\n"
        "- Community cheer zones with live music at miles 6, 13, and 20\n"
        "- Local business vendor opportunities at start/finish areas\n\n"
        "Event Details:\n"
        "- Theme: Scenic city showcase\n"
        "- Scale: 50,000 participants across 5 waves\n"
        "- Start time: 6:00 AM to avoid peak heat\n"
        "- Budget: $2.5M with projected $4M revenue from registrations and sponsors\n"
        "- Water stations every 2 miles (14 total)\n"
    )

    with patch(
        "agents.planner_with_eval.evaluator.tools._generate_feedback",
        new=AsyncMock(return_value=([], "Plan meets all evaluation criteria.")),
    ):
        with patch.dict("os.environ", {}, clear=True):
            result = await evaluate_plan(
                json.dumps(
                    {
                        "user_intent": "Plan a scenic marathon in Las Vegas for 50000 participants in April 2026",
                        "proposed_plan": realistic_plan,
                    }
                ),
            )

    assert result["eval_method"] == "heuristic"
    assert result["passed"] is True, (
        f"Realistic plan should pass evaluation. "
        f"Scores: {result['scores']}, Overall: {result['overall_score']}, "
        f"Findings: {result['findings']}"
    )
    # Verify no high-severity findings
    high_findings = [f for f in result["findings"] if f["severity"] == "high"]
    assert len(high_findings) == 0, f"Unexpected high-severity findings: {high_findings}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_realistic_plan_passes_vertex_ai_evaluation():
    """A realistic plan must pass Vertex AI Eval API when credentials are available.

    This test is skipped when GOOGLE_CLOUD_PROJECT is not set. When run,
    it proves the LLM judge scoring and planner output are in sync.
    """
    import os

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        pytest.skip("GOOGLE_CLOUD_PROJECT not set -- skipping live API test")

    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    realistic_plan = (
        "Las Vegas Marathon Plan\n\n"
        "A 26.2 mile marathon route through Las Vegas starting at the Las Vegas "
        "Sign, sweeping through the Arts District and residential neighborhoods, "
        "finishing near Michelob Ultra Arena.\n\n"
        "Safety: Emergency vehicle crossings at miles 5, 10, 15, 20. "
        "Emergency corridor access to University Medical Center. "
        "Evacuation routes every 2 miles. Medical tents at halfway and finish.\n\n"
        "Community: 30-day resident notification. Business access corridors. "
        "Equitable routing through diverse neighborhoods. Cheer zones at miles 6, 13, 20.\n\n"
        "Scale: 50,000 participants, 5 waves starting at 6 AM. "
        "Budget: $2.5M with $4M projected revenue."
    )

    result = await evaluate_plan(
        json.dumps(
            {
                "user_intent": "Plan a scenic marathon in Las Vegas for 50000 participants",
                "proposed_plan": realistic_plan,
            }
        ),
    )

    # The eval may use vertex_ai_eval or fall back to heuristic if the
    # judge model fails (e.g., location/model mismatch). Either path
    # must pass for a well-constructed plan.
    assert result["eval_method"] in ("vertex_ai_eval", "heuristic"), f"Unexpected eval method: {result['eval_method']}"
    assert result["passed"] is True, (
        f"Realistic plan should pass evaluation (method={result['eval_method']}). "
        f"Scores: {result['scores']}, Overall: {result['overall_score']}, "
        f"Findings: {result['findings']}"
    )


@pytest.mark.asyncio
async def test_evaluate_plan_invalid_json():
    """Invalid JSON input returns error with parse_error criterion."""
    from agents.planner_with_eval.evaluator.tools import evaluate_plan

    result = await evaluate_plan("not valid json")
    assert result["eval_method"] == "error"
    assert result["findings"][0]["criterion"] == "parse_error"
    assert result["overall_score"] == 0


# ---------------------------------------------------------------------------
# Wiring tests
# ---------------------------------------------------------------------------


def test_planner_tools_contain_evaluate_plan_not_evaluator_agent():
    """evaluate_plan must be a direct FunctionTool, not an AgentTool."""
    from agents.planner_with_eval.adk_tools import get_tools
    from google.adk.tools.function_tool import FunctionTool

    tools = get_tools()
    tool_names = [t.name if hasattr(t, "name") else type(t).__name__ for t in tools]

    assert "evaluate_plan" in tool_names, "evaluate_plan must be in tools"
    assert "evaluator_agent" not in tool_names, "evaluator_agent must NOT be in tools"

    eval_tool = [t for t in tools if getattr(t, "name", None) == "evaluate_plan"][0]
    assert isinstance(eval_tool, FunctionTool)


def test_evaluator_package_exports_evaluate_plan():
    """evaluator package must export evaluate_plan, not evaluator_agent."""
    from agents.planner_with_eval.evaluator import evaluate_plan as fn

    assert callable(fn)
    assert fn.__name__ == "evaluate_plan"


def test_rubric_score_5_is_achievable():
    """Score 5 rubric should say 'comprehensive' not 'excellent with strong provisions'."""
    from agents.planner_with_eval.evaluator.tools import _create_combined_llm_metric

    metric = _create_combined_llm_metric()
    prompt = str(metric.prompt_template)
    # 5 should be achievable, not perfectionist
    assert "strong provisions" not in prompt
    assert "comprehensive" in prompt.lower() or "well-addressed" in prompt.lower()


def test_combined_metric_covers_all_criteria():
    """Combined LLM metric prompt must mention all 6 criterion names."""
    from agents.planner_with_eval.evaluator.tools import (
        _create_combined_llm_metric,
        _LLM_CRITERION_SPECS,
    )

    metric = _create_combined_llm_metric()
    assert metric.name == "combined_criteria"
    prompt = metric.prompt_template
    for criterion_name in _LLM_CRITERION_SPECS:
        assert criterion_name in prompt, f"Criterion '{criterion_name}' missing from combined prompt"


# ---------------------------------------------------------------------------
# Distance compliance (miles-only) tests
# ---------------------------------------------------------------------------


class TestDistanceComplianceMilesOnly:
    """Distance compliance must only recognize miles, not km."""

    def test_exact_marathon_miles_passes(self):
        """26.2 miles should score 5.0 (perfect)."""
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        result = _check_distance_compliance_logic("The route is 26.2 miles long")
        assert result["score"] == 5.0
        assert "No distance issues" in result["explanation"]

    def test_close_marathon_miles_scores_partial(self):
        """26.0 miles (deviation 0.2) should score 3.0 (close but not exact)."""
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        result = _check_distance_compliance_logic("A 26.0 mile route through the city")
        assert result["score"] == 3.0

    def test_wrong_marathon_miles_scores_low(self):
        """25.0 miles (deviation 1.2) should score 1.0 (too far off)."""
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        result = _check_distance_compliance_logic("A 25.0 mile route through the city")
        assert result["score"] == 1.0

    def test_km_value_is_not_recognized(self):
        """42.195 km should NOT be treated as a valid marathon distance.

        Since we are miles-only, km values must be ignored entirely.
        A plan stating only km with no mile value should get the default
        score of 5.0 (no distance issues detected — the km is simply ignored).
        """
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        result = _check_distance_compliance_logic("The route is 42.195 km long")
        # km should be ignored — no mile value found, so no issues detected
        assert result["score"] == 5.0
        assert "No distance issues" in result["explanation"]

    def test_km_value_does_not_trigger_compliance(self):
        """A bad km distance (e.g., 50 km) should NOT trigger a compliance failure.

        Only miles matter. km values should be completely ignored.
        """
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        result = _check_distance_compliance_logic("The route is 50 kilometers long")
        # km should be ignored — default score, no issues
        assert result["score"] == 5.0
        assert "No distance issues" in result["explanation"]

    def test_deterministic_suggestion_miles_only(self):
        """The deterministic suggestion for distance_compliance must reference miles only."""
        from agents.planner_with_eval.evaluator.tools import _DETERMINISTIC_SUGGESTIONS

        suggestion = _DETERMINISTIC_SUGGESTIONS["distance_compliance"]
        assert "26.2 miles" in suggestion
        assert "42.195" not in suggestion
        assert "km" not in suggestion

    def test_deterministic_suggestions_cover_all_criteria(self):
        """Deterministic suggestions must have entries for all 7 criteria."""
        from agents.planner_with_eval.evaluator.tools import _DETERMINISTIC_SUGGESTIONS

        expected = {
            "safety_compliance",
            "logistics_completeness",
            "participant_experience",
            "community_impact",
            "financial_viability",
            "intent_alignment",
            "distance_compliance",
        }
        assert set(_DETERMINISTIC_SUGGESTIONS.keys()) == expected
        # plan_quality should NOT be in suggestions
        assert "plan_quality" not in _DETERMINISTIC_SUGGESTIONS

    def test_distance_compliance_metric_docstring_miles_only(self):
        """The distance compliance metric docstring must reference miles only."""
        from agents.planner_with_eval.evaluator.tools import _create_distance_compliance_metric

        docstring = _create_distance_compliance_metric.__doc__ or ""
        assert "26.2 mile" in docstring
        assert "42.195" not in docstring
        assert "km" not in docstring.lower().replace("check", "").replace("mark", "")

    def test_check_distance_compliance_logic_docstring_miles_only(self):
        """The _check_distance_compliance_logic docstring must reference miles only."""
        from agents.planner_with_eval.evaluator.tools import _check_distance_compliance_logic

        docstring = _check_distance_compliance_logic.__doc__ or ""
        assert "26.2 mile" in docstring
        assert "42.195" not in docstring
        assert " km" not in docstring


# ---------------------------------------------------------------------------
# Score normalization tests
# ---------------------------------------------------------------------------


class TestScoreNormalization:
    """Score normalization must handle both 0-1 and 1-5 ranges, outputting 0-100."""

    def test_score_on_1_to_5_scale_is_normalized(self):
        """A score of 4.0 (on 1-5 scale) should normalize to 80."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(4.0) == 80

    def test_score_on_0_to_1_scale_is_normalized(self):
        """A score of 0.8 (on 0-1 scale) should normalize to 80."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(0.8) == 80

    def test_score_zero_stays_zero(self):
        """A score of 0.0 should normalize to 0."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(0.0) == 0

    def test_score_one_normalizes_to_100(self):
        """A score of 1.0 (could be either scale) should normalize to 100.

        Note: 1.0 is ambiguous -- it could be 1/5 (worst on 1-5 scale) or
        1.0 (perfect on 0-1 scale). We treat it as already-normalized.
        See _normalize_score docstring for rationale.
        """
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(1.0) == 100

    def test_score_five_normalizes_to_100(self):
        """A score of 5.0 should normalize to 100."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(5.0) == 100

    def test_score_clamped_to_max_100(self):
        """Scores above 5.0 should be clamped to 100."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(6.0) == 100

    def test_negative_score_clamped_to_zero(self):
        """Negative scores should be clamped to 0."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        assert _normalize_score(-1.0) == 0

    def test_returns_int(self):
        """_normalize_score must return an int, not a float."""
        from agents.planner_with_eval.evaluator.tools import _normalize_score

        result = _normalize_score(3.5)
        assert isinstance(result, int)
        assert result == 70
