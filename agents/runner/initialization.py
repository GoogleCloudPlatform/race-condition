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

"""Runner initialization logic extracted from runner_autopilot.

Generates a deterministic runner profile (velocity, wall parameters,
hydration efficiency, crowd responsiveness, wave assignment) from a
seeded RNG based on the session_id. Pure state-initialization with no
dependency on the autopilot callback system.
"""

import logging
import random
from typing import Any

from agents.runner.constants import (
    LOGNORMAL_MU,
    LOGNORMAL_SIGMA,
    MARATHON_MI,
    MAX_FINISH_MIN,
    MIN_FINISH_MIN,
    SPEED_SCALE,
    WALL_HIT_PROBABILITY,
    runner_seed,
)
from agents.runner.waves import compute_wave

logger = logging.getLogger(__name__)

# State can be a plain dict (unit tests) or ADK State object (runtime).
# Both support .get(key, default). We use Any to avoid Pyright conflicts
# between dict.get() overloads and custom protocol signatures.
StateLike = Any


def initialize_runner(state: StateLike, session_id: str, runner_count: int = 1) -> None:
    """Initialize runner characteristics from seeded distributions.

    Called once during the first tick (tick 0) via ``handle_tick``. Uses a
    deterministic RNG seeded from the session_id so the same session
    always produces the same runner profile.
    """
    rng = random.Random(runner_seed(session_id))

    # Target finish time from log-normal distribution
    target_finish = rng.lognormvariate(LOGNORMAL_MU, LOGNORMAL_SIGMA)
    target_finish = max(MIN_FINISH_MIN, min(MAX_FINISH_MIN, target_finish))

    # Derive initial velocity
    target_mph = MARATHON_MI / (target_finish / 60.0)
    initial_velocity = target_mph / SPEED_SCALE

    # Wall parameters
    will_hit_wall = rng.random() < WALL_HIT_PROBABILITY
    wall_mi = rng.gauss(18.6411, 1.8641)
    wall_severity = rng.betavariate(2, 5)

    # --- Ability-scaled degradation (bell-curve) ---
    # Research: elites barely slow (0-2%), mid-pack 10-15%, walkers sustain.
    # Fast runners: low depletion (near-even pacing).
    # Mid-pack (~4h): baseline depletion (biggest degradation).
    # Slow runners: taper back (walkers maintain sustainable pace).
    ability_ratio = target_finish / 240.0  # 1.0 = 4-hour runner
    if ability_ratio <= 1.0:
        # Fast to average: efficiency scales with ability
        base_efficiency = 0.4 + 0.6 * ability_ratio  # 0.4 → 1.0
    else:
        # Slow runners: taper back toward 0.6 (walkers sustain)
        overshoot = ability_ratio - 1.0
        base_efficiency = max(0.6, 1.0 - 0.4 * overshoot)  # 1.0 → 0.6
    hydration_efficiency = max(0.3, base_efficiency * max(0.7, rng.gauss(1.0, 0.10)))

    # Crowd responsiveness: 75% of runners ignore cheering, 25% respond
    if rng.random() < 0.75:
        crowd_responsiveness = 0.0
    else:
        crowd_responsiveness = rng.betavariate(2, 5)

    # Wave start: assign corral by ability (faster runners start first)
    ability_pct = (target_finish - MIN_FINISH_MIN) / (MAX_FINISH_MIN - MIN_FINISH_MIN)
    runner_index = int(ability_pct * max(runner_count - 1, 0))
    wave_number, start_delay_minutes = compute_wave(runner_index, runner_count)

    # Starting hydration: ability-correlated, with noise, clamped to [88, 100].
    # Trained marathoners typically arrive at 97-99% of euhydration; recreational
    # runners are more variable and frequently mildly hypohydrated. See
    # docs/plans/2026-04-19-runner-starting-water-design.md for the research.
    base_water = 100.0 - 8.0 * max(0.0, ability_ratio - 0.5)
    noisy_water = base_water + rng.gauss(0.0, 1.5)
    initial_water = max(88.0, min(100.0, noisy_water))

    state["velocity"] = round(initial_velocity, 4)
    state["distance"] = 0.0
    state["water"] = round(initial_water, 4)
    state["exhausted"] = False
    state["collapsed"] = False
    state["finished"] = False
    state["runner_status"] = "running"
    state["will_hit_wall"] = will_hit_wall
    state["wall_mi"] = round(wall_mi, 4)
    state["wall_severity"] = round(wall_severity, 4)
    state["hydration_efficiency"] = round(hydration_efficiency, 4)
    state["target_finish_minutes"] = round(target_finish, 1)
    state["crowd_responsiveness"] = round(crowd_responsiveness, 4)
    state["wave_number"] = wave_number
    state["start_delay_minutes"] = start_delay_minutes
