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

"""Tests verifying runner hydration tools are the shared implementations.

Both runner and runner_autopilot re-export from agents.npc.runner_shared.hydration.
These tests confirm the re-exports resolve to the same canonical functions.
"""

from agents.npc.runner_shared import hydration as shared
from agents.npc.runner.skills.hydration import tools as runner_mod
from agents.npc.runner_autopilot.skills.hydration import tools as autopilot_mod


def test_deplete_water_is_shared():
    assert runner_mod.deplete_water is shared.deplete_water
    assert autopilot_mod.deplete_water is shared.deplete_water


def test_rehydrate_is_shared():
    assert runner_mod.rehydrate is shared.rehydrate
    assert autopilot_mod.rehydrate is shared.rehydrate
