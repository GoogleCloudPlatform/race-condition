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

from agents.runner.waves import compute_runner_wave, compute_wave


def test_small_race_no_waves():
    wave, delay = compute_wave(runner_index=25, runner_count=50)
    assert wave == 0
    assert delay == 0.0


def test_medium_race_two_waves_percentile():
    # 80 runners, threshold at 30%: index 23 (28.75%) -> wave 0, index 24 (30%) -> wave 1
    w0, d0 = compute_wave(runner_index=23, runner_count=80)
    w1, d1 = compute_wave(runner_index=24, runner_count=80)
    assert w0 == 0 and d0 == 0.0
    assert w1 == 1 and d1 == 10.0


def test_large_race_three_waves_percentile():
    # 200 runners, thresholds at 15%, 45%
    w0, d0 = compute_wave(runner_index=29, runner_count=200)  # 14.5% < 15%
    w1, d1 = compute_wave(runner_index=30, runner_count=200)  # 15% >= 15%
    w2, d2 = compute_wave(runner_index=90, runner_count=200)  # 45% >= 45%
    assert w0 == 0 and d0 == 0.0
    assert w1 == 1 and d1 == 8.0
    assert w2 == 2 and d2 == 16.0


def test_very_large_race_four_waves_percentile():
    # 1000 runners, thresholds at 10%, 30%, 60%
    w0, d0 = compute_wave(runner_index=99, runner_count=1000)  # 9.9% < 10%
    w1, d1 = compute_wave(runner_index=100, runner_count=1000)  # 10% >= 10%
    w2, d2 = compute_wave(runner_index=300, runner_count=1000)  # 30% >= 30%
    w3, d3 = compute_wave(runner_index=600, runner_count=1000)  # 60% >= 60%
    assert w0 == 0 and d0 == 0.0
    assert w1 == 1 and d1 == 7.0
    assert w2 == 2 and d2 == 14.0
    assert w3 == 3 and d3 == 21.0


def test_single_runner():
    wave, delay = compute_wave(runner_index=0, runner_count=1)
    assert wave == 0
    assert delay == 0.0


def test_compute_runner_wave_deterministic():
    """Same session_id + runner_count always produces same wave."""
    w1, _ = compute_runner_wave("test-session-abc", 1000)
    w2, _ = compute_runner_wave("test-session-abc", 1000)
    assert w1 == w2


def test_compute_runner_wave_matches_manual():
    """compute_runner_wave must match the manual computation chain."""
    import random as stdlib_random
    from agents.runner.constants import (
        runner_seed,
        LOGNORMAL_MU,
        LOGNORMAL_SIGMA,
        MIN_FINISH_MIN,
        MAX_FINISH_MIN,
    )
    from agents.runner.waves import compute_wave

    session_id = "determinism-check-xyz"
    runner_count = 1000

    rng = stdlib_random.Random(runner_seed(session_id))
    target_finish = rng.lognormvariate(LOGNORMAL_MU, LOGNORMAL_SIGMA)
    target_finish = max(MIN_FINISH_MIN, min(MAX_FINISH_MIN, target_finish))
    ability_pct = (target_finish - MIN_FINISH_MIN) / (MAX_FINISH_MIN - MIN_FINISH_MIN)
    runner_index = int(ability_pct * max(runner_count - 1, 0))
    expected_wave, _ = compute_wave(runner_index, runner_count)

    actual_wave, _ = compute_runner_wave(session_id, runner_count)
    assert actual_wave == expected_wave
