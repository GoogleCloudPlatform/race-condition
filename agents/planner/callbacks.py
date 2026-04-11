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

"""Programmatic guardrails for the planner agent."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from google.adk.models.llm_response import LlmResponse
from google.genai import types

if TYPE_CHECKING:
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models.llm_request import LlmRequest

# NOTE(caseywest): The dual-keyword approach (financial noun + write verb)
# reduces false positives vs. the old single-keyword approach, but
# co-occurrence across long messages can still trigger incorrectly
# (e.g., "road closure costs will increase traffic").  Acceptable for
# demo scope; tighten with proximity matching if needed in production.
#
# Financial-domain nouns.  Uses stem-matching (e.g. "expens" catches both
# "expense" and "expenses"; "financ" catches "financial", "financing", etc.).
_FINANCIAL_KEYWORDS = re.compile(
    r"\b(budget|financ|revenue|cost|expens|spending|profit|loss|"
    r"fund|money|dollar|invest|capital|salary|payroll|"
    r"forecast|roi|margin|debt|credit|billing)\w*\b",
    re.IGNORECASE,
)

# Write-intent verbs.  The guardrail only fires when a financial keyword
# AND a write-intent keyword co-occur in the same user message.
_WRITE_INTENT_KEYWORDS = re.compile(
    r"\b(change|increase|decrease|modify|raise|lower|cut|update|"
    r"allocate|adjust|approve|add|reduce|remove|set|slash)\b",
    re.IGNORECASE,
)

_REFUSAL_TEXT = (
    "I am not authorized to change budget allocations. "
    "The financial modeling mode is set to **secure**, which restricts "
    "modifications to all budget, revenue, and cost data. "
    "Please contact an authorized financial administrator to make budget changes."
)


def financial_guardrail_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Block budget *changes* when financial_modeling_mode is 'secure'.

    The guardrail triggers only when a user message contains both a
    financial keyword (budget, cost, ...) AND a write-intent verb
    (change, increase, ...).  Read-only financial queries pass through
    so the agent can discuss financial information freely.

    Returns a refusal LlmResponse if the guardrail triggers, or None to let
    the LLM handle the request normally.
    """
    mode = callback_context.state.get("financial_modeling_mode", "insecure")
    if mode != "secure":
        return None

    for content in reversed(llm_request.contents or []):
        if content.role != "user":
            continue
        for part in content.parts or []:
            if part.text and _FINANCIAL_KEYWORDS.search(part.text) and _WRITE_INTENT_KEYWORDS.search(part.text):
                return LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text=_REFUSAL_TEXT)],
                    ),
                )
        break

    return None
