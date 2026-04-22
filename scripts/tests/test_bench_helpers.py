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

"""Unit tests for benchmark helper functions."""

import pytest

from scripts.bench.bench_helpers import compute_percentiles, format_duration, format_bytes


class TestComputePercentiles:
    def test_basic_sorted_input(self):
        latencies = [0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.010]
        result = compute_percentiles(latencies)
        assert "p50" in result
        assert "p95" in result
        assert "p99" in result
        assert result["p50"] <= result["p95"] <= result["p99"]

    def test_single_value(self):
        result = compute_percentiles([0.042])
        assert result["p50"] == pytest.approx(0.042)
        assert result["p95"] == pytest.approx(0.042)
        assert result["p99"] == pytest.approx(0.042)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_percentiles([])

    def test_custom_percentiles(self):
        latencies = list(range(1, 101))  # 1..100
        result = compute_percentiles(latencies, percentiles=[50, 90])
        assert "p50" in result
        assert "p90" in result
        assert "p95" not in result

    def test_unsorted_input_still_works(self):
        latencies = [0.010, 0.001, 0.005, 0.003, 0.008]
        result = compute_percentiles(latencies)
        assert result["p50"] <= result["p95"]


class TestFormatDuration:
    def test_microseconds(self):
        assert format_duration(0.0005) == "500us"

    def test_milliseconds(self):
        assert format_duration(0.042) == "42.0ms"

    def test_seconds(self):
        assert format_duration(1.5) == "1.50s"

    def test_zero(self):
        assert format_duration(0.0) == "0us"

    def test_sub_microsecond(self):
        assert format_duration(0.0000001) == "0us"


class TestFormatBytes:
    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0KB"

    def test_megabytes(self):
        assert format_bytes(5 * 1024 * 1024) == "5.0MB"

    def test_gigabytes(self):
        assert format_bytes(2 * 1024 * 1024 * 1024) == "2.0GB"

    def test_bytes(self):
        assert format_bytes(500) == "500B"

    def test_zero(self):
        assert format_bytes(0) == "0B"
