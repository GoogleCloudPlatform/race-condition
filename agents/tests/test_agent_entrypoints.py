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

import sys
import unittest.mock as mock
import pytest


@pytest.mark.parametrize(
    "agent_module",
    [
        "agents.simulator.agent",
        "agents.planner.agent",
        "agents.planner_with_eval.agent",
        "agents.simulator_with_failure.agent",
        "agents.planner_with_memory.agent",
        "agents.npc.runner_autopilot.agent",
        "agents.npc.runner.agent",
    ],
)
def test_agent_main_block_smoke(agent_module):
    """
    Smoke test to ensure the __main__ block of each agent can execute without
    crashing or NameErrors, assuming external dependencies like Redis/GCP are mocked.
    """
    # 1. Mock blocking calls and external side effects
    with (
        mock.patch("uvicorn.run"),
        mock.patch("google.adk.cli.fast_api.get_fast_api_app"),
        mock.patch("agents.utils.config.load_env"),
        mock.patch("agents.simulator.agent._get_runner"),
        mock.patch("agents.planner.agent._get_runner"),
        mock.patch("agents.planner_with_eval.agent._get_runner"),
        mock.patch("agents.utils.factory.Runner"),
        mock.patch("agents.simulator_with_failure.agent._get_runner"),
        mock.patch("agents.planner_with_memory.agent._get_runner"),
        mock.patch("agents.npc.runner_autopilot.agent._get_runner"),
        mock.patch("agents.npc.runner.agent._get_runner"),
    ):
        # 2. We need to manually trigger the __main__ block logic.
        # Since 'import_module' won't run the __main__ block, we import it
        # and then manually invoke uvicorn.run if it's in the module.
        # Alternatively, we can use runpy or just verify the module loads.
        # But the USER specifically had a NameError INSIDE the __main__ block.

        # To truly test the __main__ block, we'll mock the sys.argv and __name__
        with mock.patch.object(sys, "argv", ["agent.py"]):
            try:
                # We use runpy to execute the module as __main__
                import runpy

                # This will actually execute the __main__ block
                runpy.run_module(agent_module, run_name="__main__")
            except Exception as e:
                pytest.fail(f"Agent {agent_module} failed to initialize __main__ block: {e}")

    # Success if it reached here without crashing
