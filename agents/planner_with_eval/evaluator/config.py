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

import os

# Model configuration
# Note: Use gemini-3.1-pro-preview for best results in evaluation tasks
MODEL = os.getenv("EVALUATOR_MODEL", "gemini-3.1-pro-preview")

# Criterion weights must sum to 1.0 (equal weighting)
CRITERION_WEIGHTS = {
    "safety_compliance": 1.0 / 7,
    "logistics_completeness": 1.0 / 7,
    "participant_experience": 1.0 / 7,
    "community_impact": 1.0 / 7,
    "financial_viability": 1.0 / 7,
    "intent_alignment": 1.0 / 7,
    "distance_compliance": 1.0 / 7,
}

# Evaluation criteria (6 LLM metrics + 1 deterministic)
EVALUATION_CRITERIA = [
    "safety_compliance",
    "logistics_completeness",
    "participant_experience",
    "community_impact",
    "financial_viability",
    "intent_alignment",
    "distance_compliance",
]

# Pass threshold for overall evaluation score (0-100 scale).
# A well-constructed plan (4/5 from LLM judge → 80) should reliably pass.
PASS_THRESHOLD = 75

# Severity mapping for evaluation findings (0-100 scale)
SEVERITY_THRESHOLDS = {
    "high": 40,
    "medium": 60,
    "low": 80,
}
