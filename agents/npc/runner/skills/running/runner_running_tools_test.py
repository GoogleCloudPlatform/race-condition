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

"""Tests verifying runner running tools are the shared implementations.

Both runner and runner_autopilot re-export from agents.npc.runner_shared.running.
These tests confirm the re-exports resolve to the same canonical functions.
"""

from agents.npc.runner_shared import running as shared
from agents.npc.runner.skills.running import tools as runner_mod
from agents.npc.runner_autopilot.skills.running import tools as autopilot_mod


def test_accelerate_is_shared():
    assert runner_mod.accelerate is shared.accelerate
    assert autopilot_mod.accelerate is shared.accelerate


def test_brake_is_shared():
    assert runner_mod.brake is shared.brake
    assert autopilot_mod.brake is shared.brake


def test_get_vitals_is_shared():
    assert runner_mod.get_vitals is shared.get_vitals
    assert autopilot_mod.get_vitals is shared.get_vitals


def test_process_tick_is_shared():
    assert runner_mod.process_tick is shared.process_tick
    assert autopilot_mod.process_tick is shared.process_tick
