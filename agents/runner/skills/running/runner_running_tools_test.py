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

"""Tests verifying runner running tools are the canonical implementations.

Runner skills re-export from agents.runner.running.
"""

from agents.runner import running as canonical
from agents.runner.skills.running import tools as runner_mod


def test_accelerate_is_shared():
    assert runner_mod.accelerate is canonical.accelerate


def test_brake_is_shared():
    assert runner_mod.brake is canonical.brake


def test_get_vitals_is_shared():
    assert runner_mod.get_vitals is canonical.get_vitals


def test_process_tick_is_shared():
    assert runner_mod.process_tick is canonical.process_tick
