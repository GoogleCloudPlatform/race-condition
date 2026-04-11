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

import pytest
import time
from unittest.mock import MagicMock
from google.adk.tools.tool_context import ToolContext
import importlib.util
import pathlib

# Load from the failing pre-race skill directory
_TOOLS_PATH = pathlib.Path(__file__).parent.parent / "skills" / "pre-race" / "tools.py"
_spec = importlib.util.spec_from_file_location("pre_race.tools", _TOOLS_PATH)
assert _spec is not None, f"Could not find module spec for {_TOOLS_PATH}"
assert _spec.loader is not None, f"Module spec has no loader for {_TOOLS_PATH}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
prepare_simulation = _mod.prepare_simulation


@pytest.mark.asyncio
async def test_prepare_simulation_sleeps_and_raises():
    """Verify that prepare_simulation sleeps for approx 3s and then raises RuntimeError."""
    mock_context = MagicMock(spec=ToolContext)
    mock_context.state = {}

    start_time = time.time()

    with pytest.raises(RuntimeError, match="engine failure"):
        await prepare_simulation(plan_json='{"action":"execute"}', tool_context=mock_context)

    duration = time.time() - start_time

    # Assert sleep duration was roughly 3 seconds
    assert 2.9 <= duration <= 3.5, f"Expected sleep around 3s, got {duration}s"
