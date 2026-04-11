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

"""Shared constants and utilities for NPC runner agents.

Single source of truth for marathon simulation parameters used by the
runner, runner_autopilot, and process_tick tool (per-tick physics).
"""

import hashlib

# --- Velocity / Distance ---
SPEED_SCALE = 6.2137  # velocity=1.0 maps to 6.2137 mph
MARATHON_MI = 26.2188

# --- Marathon distribution (calibrated from RunRepeat 19.6M results) ---
# Real-world average: ~4h30m. With ability-scaled degradation adding ~8-10%,
# we target a slightly faster median so effective finishes center ~4h20-4h30.
LOGNORMAL_MU = 5.45  # ln(minutes), median target ~233 min (3:53)
LOGNORMAL_SIGMA = 0.32  # Wider spread: elite (~120min) to back-of-pack (~450min)
MIN_FINISH_MIN = 120.0  # ~2:00 (allows world-class elites)
MAX_FINISH_MIN = 300.0  # 5:00 (self-selection ceiling; with degradation → ~5:30-6:00 actual)
WALL_HIT_PROBABILITY = 0.40

# --- Hydration ---
HYDRATION_STATION_INTERVAL_MI = 1.8641
HYDRATION_STATION_REFILL = 25.0
BASE_DEPLETION_RATE = 3.2187  # Water% per mile at baseline
FATIGUE_DEPLETION_GROWTH = 0.0322  # Additional depletion per mile of distance
EXHAUSTION_THRESHOLD = 30.0
COLLAPSE_THRESHOLD = 10.0

# --- Fatigue ---
NATURAL_FATIGUE_RATE = 0.002  # Velocity loss per tick (0.2%)
MIN_FATIGUE_FACTOR = 0.75  # Floor for fatigue degradation


def runner_seed(session_id: str, salt: int = 0) -> int:
    """Deterministic seed from session_id for reproducible per-runner RNG.

    Args:
        session_id: The runner's ADK session ID.
        salt: Additional salt for per-event RNG (e.g., hydration station index).

    Returns:
        Integer seed for random.Random().
    """
    return int(hashlib.sha256(f"{session_id}:{salt}".encode()).hexdigest()[:8], 16)
