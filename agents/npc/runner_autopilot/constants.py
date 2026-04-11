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

"""Backward-compatible re-export of shared runner constants.

The canonical constants now live in agents.npc.runner_shared.constants.
This module re-exports them so existing imports from
agents.npc.runner_autopilot.constants continue to work.
"""

from agents.npc.runner_shared.constants import (  # noqa: F401
    BASE_DEPLETION_RATE,
    COLLAPSE_THRESHOLD,
    EXHAUSTION_THRESHOLD,
    FATIGUE_DEPLETION_GROWTH,
    HYDRATION_STATION_INTERVAL_MI,
    HYDRATION_STATION_REFILL,
    LOGNORMAL_MU,
    LOGNORMAL_SIGMA,
    MARATHON_MI,
    MAX_FINISH_MIN,
    MIN_FATIGUE_FACTOR,
    MIN_FINISH_MIN,
    NATURAL_FATIGUE_RATE,
    SPEED_SCALE,
    WALL_HIT_PROBABILITY,
    runner_seed,
)
