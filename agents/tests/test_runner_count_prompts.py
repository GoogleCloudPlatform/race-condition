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

"""Verify planner prompts instruct the LLM to use user-requested runner count."""

from agents.planner_with_eval.prompts import PLANNER_WITH_EVAL
from agents.planner_with_memory.prompts import PLANNER_WITH_MEMORY


def test_planner_with_eval_does_not_hardcode_runner_count():
    """The planner_with_eval prompt must not hardcode a specific runner_count value."""
    instruction = PLANNER_WITH_EVAL.build()
    assert '"runner_count": 10000' not in instruction
    assert '"runner_count": 10' not in instruction
    assert "runner_count" in instruction  # Still mentioned


def test_planner_with_eval_instructs_user_runner_count():
    """The planner_with_eval prompt must instruct the LLM to use the user's count."""
    instruction = PLANNER_WITH_EVAL.build()
    lower = instruction.lower()
    # Must reference both runner_count and user's preference in same prompt
    assert "runner_count" in instruction
    assert "runner" in lower and "user" in lower, "Prompt must reference user's runner count preference"


def test_planner_with_memory_does_not_hardcode_runner_count():
    """The planner_with_memory prompt must not hardcode a specific runner_count value."""
    instruction = PLANNER_WITH_MEMORY.build()
    assert '"runner_count": 10' not in instruction
    assert "runner_count" in instruction  # Still mentioned


def test_planner_with_memory_instructs_user_runner_count():
    """The planner_with_memory prompt must instruct the LLM to use the user's count."""
    instruction = PLANNER_WITH_MEMORY.build()
    lower = instruction.lower()
    # Must reference both runner_count and user's preference in same prompt
    assert "runner_count" in instruction
    assert "runner" in lower and "user" in lower, "Prompt must reference user's runner count preference"
