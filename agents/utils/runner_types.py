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

"""Runner type constants for simulation agent selection.

The simulator defaults to runner_autopilot (deterministic, no LLM).
The planner can request a different type via simulation_config.
"""

import os

RUNNER_AUTOPILOT = "runner_autopilot"
RUNNER_CLOUDRUN = "runner_cloudrun"
RUNNER_GKE = "runner_gke"
RUNNER = "runner"

DEFAULT_RUNNER_TYPE = RUNNER_AUTOPILOT

ALL_RUNNER_TYPES = (
    RUNNER_AUTOPILOT,
    RUNNER_CLOUDRUN,
    RUNNER_GKE,
    RUNNER,
)

LLM_RUNNER_TYPES = (RUNNER, RUNNER_CLOUDRUN, RUNNER_GKE)


def cap_for_runner_type(runner_type: str) -> int:
    """Return the configured runner-count cap for the given runner_type.

    The cap is read from environment variables at call time so that deploy-time
    overrides (.env.{env} files) take effect without code changes:

    - ``runner_autopilot`` → ``MAX_RUNNERS_AUTOPILOT`` (default ``100``)
    - any LLM runner type → ``MAX_RUNNERS_LLM`` (default ``10``)

    Defaults are local-friendly. GCP deployments override via ``.env.dev``
    (autopilot=1000, LLM=100). Unknown runner types fall through to the LLM
    cap as a defensive default — better undersized than uncapped.
    """
    if runner_type == RUNNER_AUTOPILOT:
        return int(os.environ.get("MAX_RUNNERS_AUTOPILOT", "100"))
    return int(os.environ.get("MAX_RUNNERS_LLM", "10"))
