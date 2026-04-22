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

"""Wave start assignment for corral-based marathon starts."""

import random

from agents.runner.constants import (
    LOGNORMAL_MU,
    LOGNORMAL_SIGMA,
    MAX_FINISH_MIN,
    MIN_FINISH_MIN,
    runner_seed,
)

_WAVE_CONFIG: list[tuple[list[float], float]] = [
    # (cumulative_percentile_thresholds, gap_minutes)
    # 2 waves: 30% fast / 70% back
    ([0.30], 10.0),
    # 3 waves: 15% fast / 30% mid / 55% back
    ([0.15, 0.45], 8.0),
    # 4 waves: 10% elite / 20% fast / 30% mid / 40% back
    ([0.10, 0.30, 0.60], 7.0),
]


def compute_wave(runner_index: int, runner_count: int) -> tuple[int, float]:
    """Compute wave number and start delay for a runner.

    Wave sizes follow real marathon corral distributions: a small elite
    group up front, progressively larger groups behind.

    Args:
        runner_index: Runner's position (0-based) sorted by ability.
        runner_count: Total number of runners.

    Returns:
        Tuple of (wave_number, start_delay_minutes) in simulated race time.
    """
    if runner_count <= 50:
        return 0, 0.0

    if runner_count <= 100:
        thresholds, gap = _WAVE_CONFIG[0]
    elif runner_count <= 250:
        thresholds, gap = _WAVE_CONFIG[1]
    else:
        thresholds, gap = _WAVE_CONFIG[2]

    pct = runner_index / max(runner_count, 1)
    wave = len(thresholds)  # default: last wave
    for i, t in enumerate(thresholds):
        if pct < t:
            wave = i
            break
    return wave, wave * gap


def compute_runner_wave(session_id: str, runner_count: int) -> tuple[int, float]:
    """Compute a runner's wave from session_id and runner_count.

    Replicates the ability-based wave assignment from initialize_runner
    so the simulator can build wave groupings without runner state access.
    """
    rng = random.Random(runner_seed(session_id))
    target_finish = rng.lognormvariate(LOGNORMAL_MU, LOGNORMAL_SIGMA)
    target_finish = max(MIN_FINISH_MIN, min(MAX_FINISH_MIN, target_finish))
    ability_pct = (target_finish - MIN_FINISH_MIN) / (MAX_FINISH_MIN - MIN_FINISH_MIN)
    runner_index = int(ability_pct * max(runner_count - 1, 0))
    return compute_wave(runner_index, runner_count)
