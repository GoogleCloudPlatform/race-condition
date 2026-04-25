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

"""Tests verifying runner managing-hydration tools re-export the canonical implementations.

The skill directory has a hyphenated name (``managing-hydration``) so the
tools module is loaded via ``importlib.util.spec_from_file_location``
rather than a normal ``import`` statement.
"""

import importlib.util
import pathlib

from agents.runner import hydration as canonical


def _load_skill_tools():
    tools_path = pathlib.Path(__file__).parent / "tools.py"
    spec = importlib.util.spec_from_file_location(
        "managing_hydration.tools", tools_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_runner_mod = _load_skill_tools()


def test_deplete_water_is_shared():
    assert _runner_mod.deplete_water is canonical.deplete_water


def test_rehydrate_is_shared():
    assert _runner_mod.rehydrate is canonical.rehydrate
