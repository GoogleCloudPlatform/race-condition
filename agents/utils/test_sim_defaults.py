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

"""Tests for agents.utils.sim_defaults."""

import importlib
import os

import pytest


def _reload_with_env(env: dict[str, str]):
    """Reload sim_defaults with the given environment overrides."""
    import agents.utils.sim_defaults as mod

    orig = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        importlib.reload(mod)
        return mod
    finally:
        for k, v in orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _reload_clean():
    """Reload sim_defaults with no env overrides (uses built-in defaults)."""
    import agents.utils.sim_defaults as mod

    for key in ("SIM_DEFAULT_DURATION_SECONDS", "SIM_DEFAULT_TICK_INTERVAL_SECONDS"):
        os.environ.pop(key, None)
    importlib.reload(mod)
    return mod


class TestNearestDivisor:
    """Unit tests for the _nearest_divisor helper."""

    def test_exact_divisor(self):
        from agents.utils.sim_defaults import _nearest_divisor

        assert _nearest_divisor(60, 10) == 10

    def test_not_a_divisor_adjusts_down(self):
        from agents.utils.sim_defaults import _nearest_divisor

        # 7 doesn't divide 60; nearest divisor <= 7 is 6
        assert _nearest_divisor(60, 7) == 6

    def test_prime_duration(self):
        from agents.utils.sim_defaults import _nearest_divisor

        # 59 is prime; only divisors are 1 and 59
        assert _nearest_divisor(59, 10) == 1

    def test_one_always_works(self):
        from agents.utils.sim_defaults import _nearest_divisor

        assert _nearest_divisor(60, 1) == 1

    def test_tick_equals_duration(self):
        from agents.utils.sim_defaults import _nearest_divisor

        assert _nearest_divisor(60, 60) == 60

    def test_tick_larger_than_duration(self):
        from agents.utils.sim_defaults import _nearest_divisor

        # tick_interval > duration: largest divisor of 60 that is <= 120 is 60
        assert _nearest_divisor(60, 120) == 60

    def test_various_adjustments(self):
        from agents.utils.sim_defaults import _nearest_divisor

        # 60's divisors: 1,2,3,4,5,6,10,12,15,20,30,60
        assert _nearest_divisor(60, 11) == 10
        assert _nearest_divisor(60, 9) == 6
        assert _nearest_divisor(60, 14) == 12
        assert _nearest_divisor(60, 19) == 15
        assert _nearest_divisor(60, 29) == 20


class TestModuleDefaults:
    """Test that module-level constants are correct with default env."""

    def test_defaults_without_env(self):
        mod = _reload_clean()
        assert mod.DEFAULT_DURATION_SECONDS == 120
        assert mod.DEFAULT_TICK_INTERVAL_SECONDS == 10
        assert mod.DEFAULT_MAX_TICKS == 12

    def test_clean_division(self):
        mod = _reload_clean()
        assert mod.DEFAULT_DURATION_SECONDS % mod.DEFAULT_TICK_INTERVAL_SECONDS == 0


class TestEnvOverrides:
    """Test that env vars are respected and normalization applies."""

    def test_custom_duration_and_tick(self):
        mod = _reload_with_env({"SIM_DEFAULT_DURATION_SECONDS": "120", "SIM_DEFAULT_TICK_INTERVAL_SECONDS": "20"})
        assert mod.DEFAULT_DURATION_SECONDS == 120
        assert mod.DEFAULT_TICK_INTERVAL_SECONDS == 20
        assert mod.DEFAULT_MAX_TICKS == 6

    def test_normalization_adjusts_tick(self):
        mod = _reload_with_env({"SIM_DEFAULT_DURATION_SECONDS": "60", "SIM_DEFAULT_TICK_INTERVAL_SECONDS": "7"})
        assert mod.DEFAULT_DURATION_SECONDS == 60
        # 7 doesn't divide 60; adjusted to 6
        assert mod.DEFAULT_TICK_INTERVAL_SECONDS == 6
        assert mod.DEFAULT_MAX_TICKS == 10

    def test_only_duration_override(self):
        mod = _reload_with_env({"SIM_DEFAULT_DURATION_SECONDS": "120"})
        assert mod.DEFAULT_DURATION_SECONDS == 120
        assert mod.DEFAULT_TICK_INTERVAL_SECONDS == 10
        assert mod.DEFAULT_MAX_TICKS == 12

    def test_only_tick_override(self):
        mod = _reload_with_env({"SIM_DEFAULT_TICK_INTERVAL_SECONDS": "5"})
        assert mod.DEFAULT_DURATION_SECONDS == 120
        assert mod.DEFAULT_TICK_INTERVAL_SECONDS == 5
        assert mod.DEFAULT_MAX_TICKS == 24

    def test_max_ticks_always_whole(self):
        """Normalization guarantees integer division with zero remainder."""
        mod = _reload_with_env({"SIM_DEFAULT_DURATION_SECONDS": "90", "SIM_DEFAULT_TICK_INTERVAL_SECONDS": "7"})
        assert mod.DEFAULT_DURATION_SECONDS % mod.DEFAULT_TICK_INTERVAL_SECONDS == 0
        assert mod.DEFAULT_MAX_TICKS == mod.DEFAULT_DURATION_SECONDS // mod.DEFAULT_TICK_INTERVAL_SECONDS

    @pytest.fixture(autouse=True)
    def _restore_defaults(self):
        """Restore module defaults after each test."""
        yield
        _reload_clean()
