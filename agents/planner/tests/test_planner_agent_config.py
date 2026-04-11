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

"""Regression: planner LlmAgent must pin a thinking_budget.

Without this, gemini-3-flash-preview defaults to dynamic thinking and can
emit a thought_signature Part with text=None on terminal turns, leaving
the chat empty -- the actual root cause of the Demo 1 "no narrative"
regression.
"""


def test_planner_has_thinking_budget_set():
    """Planner MUST set thinking_config to externalize narrative.

    Without this, gemini-3-flash-preview defaults to dynamic thinking and
    can emit a thought_signature Part with text=None on terminal turns.
    The result is empty terminal model turns and no narrative reaching
    the chat UI. Demo 1 regression -- see commit message body for details.

    planner_with_eval uses thinking_budget=1024 and works correctly;
    runner/simulator use thinking_budget=0 (no thinking, also works).
    Planner uses 1024 to allow reasoning while forcing externalization.
    """
    from agents.planner.agent import root_agent

    cfg = root_agent.generate_content_config
    assert cfg is not None, "Planner must declare a generate_content_config"
    assert cfg.thinking_config is not None, (
        "Planner must set thinking_config; default behavior emits thought_signature without externalized text."
    )
    assert cfg.thinking_config.thinking_budget == 1024


def test_planner_max_output_tokens_is_8192():
    """Planner MUST set max_output_tokens=8192 to avoid Gemini's default cap.

    Without an explicit max_output_tokens, Gemini's default applies. Combined
    with thinking_budget=1024 consuming part of the per-turn token budget,
    the model can run out of tokens before emitting terminal text on
    post-tool continuation turns. ADK observes a short or empty response
    and exits the loop. No terminal text reaches chat (Bug B).

    The empirically-working agent (planner_with_eval) sets
    max_output_tokens=8192 explicitly. See
    docs/plans/2026-04-18-planner-max-output-tokens-design.md.
    """
    from agents.planner.agent import root_agent

    cfg = root_agent.generate_content_config
    assert cfg is not None, "Planner must declare a generate_content_config"
    assert cfg.max_output_tokens == 8192, (
        f"Planner must set max_output_tokens=8192. Currently: {cfg.max_output_tokens!r}"
    )
