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

"""Regression: planner_with_memory LlmAgent must pin a thinking_budget.

Without this, gemini-3-flash-preview defaults to dynamic thinking and can
emit a thought_signature Part with text=None on terminal turns, leaving
the chat empty. The base planner was fixed in commit 1555150e; the open
follow-up to extend the fix to the eval/memory variants is recorded in
docs/plans/2026-04-18-bug-b-investigation-handoff.md:327-331.
"""


def test_planner_with_memory_has_thinking_budget_set():
    """planner_with_memory MUST set thinking_config to externalize narrative.

    Mirrors agents/planner/tests/test_planner_agent_config.py.
    """
    from agents.planner_with_memory.agent import root_agent

    cfg = root_agent.generate_content_config
    assert cfg is not None, "planner_with_memory must declare a generate_content_config"
    assert cfg.thinking_config is not None, (
        "planner_with_memory must set thinking_config; default behavior emits "
        "thought_signature without externalized text on gemini-3-flash-preview."
    )
    assert cfg.thinking_config.thinking_budget == 1024


def test_planner_with_memory_max_output_tokens_is_8192():
    """planner_with_memory MUST set max_output_tokens=8192."""
    from agents.planner_with_memory.agent import root_agent

    cfg = root_agent.generate_content_config
    assert cfg is not None, "planner_with_memory must declare a generate_content_config"
    assert cfg.max_output_tokens == 8192, (
        f"planner_with_memory must set max_output_tokens=8192. Currently: {cfg.max_output_tokens!r}"
    )
