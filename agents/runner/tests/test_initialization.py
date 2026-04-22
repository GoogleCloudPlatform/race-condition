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

"""Tests for runner initialization (extracted from autopilot)."""

from agents.runner.initialization import initialize_runner


class TestInitializeRunner:
    def test_importable(self):
        assert callable(initialize_runner)

    def test_sets_velocity_from_lognormal(self):
        state = {}
        initialize_runner(state, "test-session-123", 10)
        assert state["velocity"] is not None
        assert state["velocity"] > 0

    def test_sets_wall_parameters(self):
        state = {}
        initialize_runner(state, "test-session-wall", 10)
        assert "will_hit_wall" in state
        assert "wall_mi" in state
        assert "wall_severity" in state

    def test_deterministic_per_session_id(self):
        s1, s2 = {}, {}
        initialize_runner(s1, "deterministic-test", 10)
        initialize_runner(s2, "deterministic-test", 10)
        assert s1["velocity"] == s2["velocity"]
        assert s1["will_hit_wall"] == s2["will_hit_wall"]

    def test_different_sessions_get_different_values(self):
        s1, s2 = {}, {}
        initialize_runner(s1, "session-alpha", 10)
        initialize_runner(s2, "session-beta", 10)
        # With different seeds, at least velocity should differ
        assert s1["velocity"] != s2["velocity"]

    def test_sets_runner_status(self):
        state = {}
        initialize_runner(state, "status-test", 10)
        assert state["runner_status"] == "running"
        assert state["finished"] is False
        assert state["collapsed"] is False

    def test_sets_hydration_and_crowd(self):
        state = {}
        initialize_runner(state, "hydration-test", 10)
        assert "hydration_efficiency" in state
        assert "crowd_responsiveness" in state
        assert 0.0 <= state["hydration_efficiency"] <= 2.0
        assert 0.0 <= state["crowd_responsiveness"] <= 1.0

    def test_sets_wave_assignment(self):
        state = {}
        initialize_runner(state, "wave-test", 100)
        assert "wave_number" in state
        assert "start_delay_minutes" in state
        assert isinstance(state["wave_number"], int)

    def test_starting_water_in_realistic_range(self):
        # Realistic marathon starting hydration is in [88, 100] %.
        for i in range(50):
            state = {}
            initialize_runner(state, f"water-range-session-{i}", 50)
            assert 88.0 <= state["water"] <= 100.0, f"water={state['water']} out of [88, 100] for session {i}"

    def test_starting_water_deterministic_per_session(self):
        s1, s2 = {}, {}
        initialize_runner(s1, "water-determinism", 10)
        initialize_runner(s2, "water-determinism", 10)
        assert s1["water"] == s2["water"]

    def test_starting_water_not_constant(self):
        # Regression guard against a constant-100 default.
        values = set()
        for i in range(50):
            state = {}
            initialize_runner(state, f"water-variance-session-{i}", 50)
            values.add(state["water"])
        assert len(values) > 30, f"expected >30 distinct starting water values across 50 sessions, got {len(values)}"

    def test_starting_water_correlates_with_ability(self):
        # Faster runners (lower target_finish_minutes) should, on average,
        # start with higher hydration than slower runners.
        runners = []
        for i in range(200):
            state = {}
            initialize_runner(state, f"water-ability-session-{i}", 200)
            runners.append((state["target_finish_minutes"], state["water"]))
        runners.sort(key=lambda r: r[0])
        fast_half = runners[: len(runners) // 2]
        slow_half = runners[len(runners) // 2 :]
        fast_mean = sum(w for _, w in fast_half) / len(fast_half)
        slow_mean = sum(w for _, w in slow_half) / len(slow_half)
        assert fast_mean > slow_mean, (
            f"fast cohort mean ({fast_mean:.2f}) not greater than slow cohort mean ({slow_mean:.2f})"
        )
