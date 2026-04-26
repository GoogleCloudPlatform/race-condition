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

"""Regression test for PR #53 follow-up: ``agents/conftest.py`` must pin its
test env vars even when the host shell exports conflicting values via the
Makefile's ``-include .env / export``.

Spawned in a subprocess to control the inherited environment deterministically.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_conftest_pins_env_against_host_leakage():
    repo_root = Path(__file__).resolve().parents[2]
    keys = [
        "GOOGLE_CLOUD_PROJECT",
        "PROJECT_ID",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_CLOUD_AGENT_ENGINE_ID",
        "ALLOYDB_HOST",
        "SECRET_MANAGER_PROJECT",
    ]
    hostile = {
        **os.environ,
        "GOOGLE_CLOUD_PROJECT": "hostile-project",
        "PROJECT_ID": "hostile-project",
        "GOOGLE_CLOUD_LOCATION": "hostile-region",
        "GOOGLE_CLOUD_AGENT_ENGINE_ID": "hostile-engine",
        "ALLOYDB_HOST": "hostile-host",
        "SECRET_MANAGER_PROJECT": "hostile-sm-project",
    }
    script = (
        "import os, json, sys, agents.conftest\n"
        "json.dump({k: os.environ.get(k) for k in sys.argv[1:]}, sys.stdout)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, *keys],
        env=hostile,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    assert data["GOOGLE_CLOUD_PROJECT"] == "test-project"
    assert data["PROJECT_ID"] == "test-project"
    assert data["GOOGLE_CLOUD_LOCATION"] == "global"
    assert data["GOOGLE_CLOUD_AGENT_ENGINE_ID"] == "test-agent-engine"
    assert data["ALLOYDB_HOST"] == "127.0.0.1"
    assert data["SECRET_MANAGER_PROJECT"] is None
