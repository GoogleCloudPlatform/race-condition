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

"""Integration test for Vertex AI Eval LLM metrics.

Calls the real Vertex AI Eval API to verify that LLM metrics produce
scores without 400 errors. Requires GOOGLE_CLOUD_PROJECT and network access.
"""

import os

import pandas as pd
import pytest
import vertexai
from google.genai import types as genai_types

from agents.planner_with_eval.evaluator.tools import (
    _create_combined_llm_metric,
    _create_distance_compliance_metric,
    _LLM_CRITERION_SPECS,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_SAMPLE_INTENT = "Plan a spring marathon in Las Vegas for 10,000 runners with a moderate budget and scenic theme."

_SAMPLE_PLAN = """\
# Neon & Neighborhoods Marathon

## Route
The 26.2-mile route starts at the Las Vegas Sign, runs north along the
Las Vegas Strip past MGM Grand and the Bellagio Fountains, continues through
local neighborhoods and Sunset Park, and finishes near Michelob Ultra Arena.

## Logistics
- Start time: 6:00 AM (heat mitigation)
- 14 water stations every ~2 miles
- 2 nutrition stations at miles 10 and 20
- 500 course marshals, 200+ police officers
- RFID chip timing at 5km intervals
- 4 start waves to manage congestion

## Safety
- Medical tents at halfway (mile 13) and finish
- Mobile bike medics patrolling the course
- Emergency vehicle crossing points at Sahara & Las Vegas Blvd
- Hospital access corridors for Sunrise Hospital and UMC
- Evacuation routes via non-closed side streets

## Community
- 6:00 AM start minimizes residential disruption
- Neighborhood roads reopen by 10:00 AM
- Local business "Cheer Zones" with runner discounts
- Route through diverse neighborhoods for equity

## Financial
- Registration fee: $150 per runner ($1.5M projected revenue)
- Tiered sponsorships: Title, Gold, Silver
- Moderate budget: prioritize safety and high-impact amenities
- 200 porta-potties at start, 100 at finish, 4 per aid station

## Experience
- Scenic route past world-class landmarks
- Live local bands and DJs every 5 miles
- Post-race festival at finish line
- High-quality medals and moisture-wicking shirts
"""


@pytest.fixture
def vertex_client():
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        pytest.skip("GOOGLE_CLOUD_PROJECT not set")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    vertexai.init(project=project_id, location=location)
    return vertexai.Client(  # type: ignore[attr-defined]
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )


def test_combined_metric_returns_all_scores(vertex_client):
    """Single combined LLM metric returns scores for all 6 criteria.

    This replaces 6 separate evaluateInstances calls (~194s) with 1 call.
    The test asserts correctness AND measures wall time.
    """
    import json
    import time

    df = pd.DataFrame({"prompt": [_SAMPLE_INTENT], "response": [_SAMPLE_PLAN]})

    combined = _create_combined_llm_metric()
    all_metrics = [combined, _create_distance_compliance_metric()]

    t0 = time.perf_counter()
    result = vertex_client.evals.evaluate(dataset=df, metrics=all_metrics)
    elapsed = time.perf_counter() - t0

    print(f"\n=== Combined metric eval took {elapsed:.1f}s ===")

    assert result.eval_case_results, "No eval case results returned"
    case = result.eval_case_results[0]
    assert case.response_candidate_results, "No response candidate results"
    cand = case.response_candidate_results[0]

    # Distance compliance should have its own result
    dc = cand.metric_results.get("distance_compliance")
    assert dc is not None, "distance_compliance metric missing"
    assert dc.score is not None, f"distance_compliance has no score: {getattr(dc, 'error_message', None)}"

    # Combined criteria should have a score and explanation
    cc = cand.metric_results.get("combined_criteria")
    assert cc is not None, f"combined_criteria metric missing. Got: {list(cand.metric_results.keys())}"
    assert getattr(cc, "error_message", None) is None, f"combined_criteria error: {cc.error_message}"
    assert cc.score is not None, "combined_criteria has no overall score"
    assert cc.explanation, "combined_criteria has no explanation"

    print(f"Overall score: {cc.score}")
    print(f"Explanation: {cc.explanation!r}")

    # Extract per-criterion scores from explanation using same logic as
    # production code (_run_custom_eval). The explanation contains per-criterion
    # scores, either as valid JSON or as key: value text.
    extracted: dict[str, int] = {}
    try:
        parsed = json.loads(cc.explanation)
        if isinstance(parsed, dict):
            extracted = {k: int(v) for k, v in parsed.items() if k in _LLM_CRITERION_SPECS}
    except (json.JSONDecodeError, ValueError, TypeError):
        import re

        for criterion_name in _LLM_CRITERION_SPECS:
            match = re.search(rf'["\']?{criterion_name}["\']?\s*:\s*(\d)', cc.explanation)
            if match:
                extracted[criterion_name] = int(match.group(1))

    print(f"Extracted scores: {extracted}")

    for criterion_name in _LLM_CRITERION_SPECS:
        assert criterion_name in extracted, f"Missing criterion '{criterion_name}' in: {cc.explanation!r}"
        score = extracted[criterion_name]
        assert 1 <= score <= 5, f"Score for '{criterion_name}' out of range: {score}"

    # Performance: combined should be under 60s (was ~194s with 6 separate)
    assert elapsed < 60, f"Combined eval took {elapsed:.1f}s -- expected < 60s"
