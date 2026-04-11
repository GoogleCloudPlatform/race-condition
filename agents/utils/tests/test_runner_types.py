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

"""Tests for runner type constants."""

import pytest

from agents.utils.runner_types import (
    ALL_RUNNER_TYPES,
    DEFAULT_RUNNER_TYPE,
    LLM_RUNNER_TYPES,
    RUNNER,
    RUNNER_AUTOPILOT,
    RUNNER_CLOUDRUN,
    RUNNER_GKE,
    cap_for_runner_type,
)


def test_default_runner_type_is_runner_autopilot():
    assert DEFAULT_RUNNER_TYPE == "runner_autopilot"


def test_all_runner_types_contains_all_constants():
    assert RUNNER_AUTOPILOT in ALL_RUNNER_TYPES
    assert RUNNER_CLOUDRUN in ALL_RUNNER_TYPES
    assert RUNNER_GKE in ALL_RUNNER_TYPES
    assert RUNNER in ALL_RUNNER_TYPES


def test_all_runner_types_length():
    assert len(ALL_RUNNER_TYPES) == 4


def test_runner_type_values():
    assert RUNNER_AUTOPILOT == "runner_autopilot"
    assert RUNNER_CLOUDRUN == "runner_cloudrun"
    assert RUNNER_GKE == "runner_gke"
    assert RUNNER == "runner"


class TestLLMRunnerTypes:
    def test_contains_exactly_the_three_llm_types(self):
        assert set(LLM_RUNNER_TYPES) == {RUNNER, RUNNER_CLOUDRUN, RUNNER_GKE}

    def test_does_not_contain_autopilot(self):
        assert RUNNER_AUTOPILOT not in LLM_RUNNER_TYPES


class TestCapForRunnerType:
    def test_autopilot_default_cap_is_100(self, monkeypatch):
        monkeypatch.delenv("MAX_RUNNERS_AUTOPILOT", raising=False)
        assert cap_for_runner_type(RUNNER_AUTOPILOT) == 100

    def test_llm_default_cap_is_10(self, monkeypatch):
        monkeypatch.delenv("MAX_RUNNERS_LLM", raising=False)
        assert cap_for_runner_type(RUNNER) == 10

    @pytest.mark.parametrize("rtype", [RUNNER, RUNNER_CLOUDRUN, RUNNER_GKE])
    def test_all_llm_types_use_llm_cap(self, monkeypatch, rtype):
        monkeypatch.setenv("MAX_RUNNERS_LLM", "42")
        assert cap_for_runner_type(rtype) == 42

    def test_autopilot_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_RUNNERS_AUTOPILOT", "777")
        assert cap_for_runner_type(RUNNER_AUTOPILOT) == 777

    def test_llm_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_RUNNERS_LLM", "55")
        assert cap_for_runner_type(RUNNER) == 55

    def test_autopilot_and_llm_caps_are_independent(self, monkeypatch):
        monkeypatch.setenv("MAX_RUNNERS_AUTOPILOT", "200")
        monkeypatch.setenv("MAX_RUNNERS_LLM", "20")
        assert cap_for_runner_type(RUNNER_AUTOPILOT) == 200
        assert cap_for_runner_type(RUNNER) == 20

    def test_unknown_type_falls_through_to_llm_cap_safely(self, monkeypatch):
        """Defensive default: unknown runner_type gets the lower (safer) LLM cap."""
        monkeypatch.setenv("MAX_RUNNERS_LLM", "10")
        assert cap_for_runner_type("runner_future_variant") == 10
