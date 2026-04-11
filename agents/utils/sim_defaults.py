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

"""Centralized simulation defaults.

Default simulation duration and tick interval are read from environment
variables at import time.  If ``SIM_DEFAULT_TICK_INTERVAL_SECONDS`` does
not evenly divide ``SIM_DEFAULT_DURATION_SECONDS``, the tick interval is
silently adjusted down to the nearest clean divisor so that
``duration / tick_interval`` always yields a whole number of ticks.

Environment variables
---------------------
``SIM_DEFAULT_DURATION_SECONDS``
    Total wall-clock seconds for one simulation run (default **120**).
``SIM_DEFAULT_TICK_INTERVAL_SECONDS``
    Seconds between ticks (default **10**).
"""

import os


def _nearest_divisor(duration: int, tick_interval: int) -> int:
    """Return the largest divisor of *duration* that is <= *tick_interval*.

    This guarantees ``duration % result == 0``.  Falls back to 1 if no
    larger divisor qualifies.
    """
    for candidate in range(tick_interval, 0, -1):
        if duration % candidate == 0:
            return candidate
    return 1  # pragma: no cover – 1 always divides anything


_raw_duration = int(os.environ.get("SIM_DEFAULT_DURATION_SECONDS", "120"))
_raw_tick = int(os.environ.get("SIM_DEFAULT_TICK_INTERVAL_SECONDS", "10"))

DEFAULT_DURATION_SECONDS: int = _raw_duration
DEFAULT_TICK_INTERVAL_SECONDS: int = _nearest_divisor(_raw_duration, _raw_tick)
DEFAULT_MAX_TICKS: int = DEFAULT_DURATION_SECONDS // DEFAULT_TICK_INTERVAL_SECONDS
