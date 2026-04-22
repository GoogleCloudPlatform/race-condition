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

"""Verify all runner agents use include_contents='none'.

Runner state is carried in tool_context.state (key-value dict),
not in conversation history. include_contents='none' prevents O(ticks)
session history growth causing progressive tick latency degradation.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_path",
    [
        "agents.runner.agent",
        "agents.runner_autopilot.agent",
    ],
    ids=["runner", "runner_autopilot"],
)
def test_runner_include_contents_none(module_path):
    """LLM runners must not accumulate conversation history."""
    mod = importlib.import_module(module_path)
    agent = mod.root_agent
    assert agent.include_contents == "none", (
        f"Expected include_contents='none' for {module_path}, "
        f"got '{agent.include_contents}'. Without this, session history "
        "grows O(ticks) causing progressive tick latency degradation."
    )
