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

"""Helper functions for the concurrency benchmark."""

from collections.abc import Sequence


def compute_percentiles(
    latencies: Sequence[float],
    percentiles: Sequence[int] | None = None,
) -> dict[str, float]:
    """Compute percentile values from a list of latencies.

    Args:
        latencies: List of latency values in seconds.
        percentiles: Which percentiles to compute (default: [50, 95, 99]).

    Returns:
        Dict mapping "p{N}" to the percentile value.

    Raises:
        ValueError: If latencies is empty.
    """
    if not latencies:
        raise ValueError("latencies must not be empty")

    if percentiles is None:
        percentiles = [50, 95, 99]

    sorted_lats = sorted(latencies)
    n = len(sorted_lats)
    result = {}
    for p in percentiles:
        idx = max(0, min(n - 1, int(n * p / 100)))
        result[f"p{p}"] = sorted_lats[idx]
    return result


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}us"
    elif seconds < 1.0:
        return f"{seconds * 1_000:.1f}ms"
    else:
        return f"{seconds:.2f}s"


def format_bytes(num_bytes: int) -> str:
    """Format byte count to human-readable string."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.1f}GB"
