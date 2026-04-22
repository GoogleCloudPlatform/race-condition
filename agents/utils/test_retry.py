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

"""Tests for agents.utils.retry module."""

import os
from unittest import mock

import pytest
from google.genai import types


class TestDefaultRetryOptions:
    """Tests for default_retry_options()."""

    def test_returns_http_retry_options(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert isinstance(opts, types.HttpRetryOptions)

    def test_default_attempts(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert opts.attempts == 5

    def test_default_initial_delay(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert opts.initial_delay == 1.0

    def test_default_max_delay(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert opts.max_delay == 60.0

    def test_default_exp_base(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert opts.exp_base == 2.0

    def test_default_jitter(self):
        from agents.utils.retry import default_retry_options

        opts = default_retry_options()
        assert opts.jitter == 1.0

    def test_env_var_overrides_attempts(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_ATTEMPTS": "10"}):
            opts = default_retry_options()
        assert opts.attempts == 10

    def test_env_var_overrides_initial_delay(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_INITIAL_DELAY": "2.5"}):
            opts = default_retry_options()
        assert opts.initial_delay == 2.5

    def test_env_var_overrides_max_delay(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_MAX_DELAY": "120.0"}):
            opts = default_retry_options()
        assert opts.max_delay == 120.0

    def test_invalid_attempts_raises_valueerror(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_ATTEMPTS": "invalid"}):
            with pytest.raises(ValueError, match="GEMINI_RETRY_ATTEMPTS.*not a valid integer"):
                default_retry_options()

    def test_zero_attempts_raises_valueerror(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_ATTEMPTS": "0"}):
            with pytest.raises(ValueError, match="GEMINI_RETRY_ATTEMPTS.*must be >= 1"):
                default_retry_options()

    def test_invalid_delay_raises_valueerror(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_INITIAL_DELAY": "not-a-number"}):
            with pytest.raises(ValueError, match="GEMINI_RETRY_INITIAL_DELAY.*not a valid number"):
                default_retry_options()

    def test_negative_delay_raises_valueerror(self):
        from agents.utils.retry import default_retry_options

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_INITIAL_DELAY": "-1.0"}):
            with pytest.raises(ValueError, match="GEMINI_RETRY_INITIAL_DELAY.*must be >= 0"):
                default_retry_options()


class TestResilientModel:
    """Tests for resilient_model()."""

    def test_returns_global_gemini_instance(self):
        from agents.utils.global_gemini import GlobalGemini
        from agents.utils.retry import resilient_model

        model = resilient_model("gemini-3-flash-preview")
        assert isinstance(model, GlobalGemini)

    def test_model_name_is_set(self):
        from agents.utils.retry import resilient_model

        model = resilient_model("gemini-3-flash-preview")
        assert model.model == "gemini-3-flash-preview"

    def test_retry_options_are_applied(self):
        from agents.utils.retry import resilient_model

        model = resilient_model("gemini-3-flash-preview")
        assert model.retry_options is not None
        assert model.retry_options.attempts == 5

    def test_custom_retry_options(self):
        from agents.utils.retry import resilient_model

        custom = types.HttpRetryOptions(attempts=3, initial_delay=0.5)
        model = resilient_model("gemini-3-flash-preview", retry_options=custom)
        assert model.retry_options is not None
        assert model.retry_options.attempts == 3
        assert model.retry_options.initial_delay == 0.5

    def test_default_location_is_global(self):
        from agents.utils.retry import resilient_model

        model = resilient_model("gemini-3-flash-preview")
        assert model.location == "global"

    def test_custom_location(self):
        from agents.utils.retry import resilient_model

        model = resilient_model("gemini-2.0-flash", location="us-central1")
        assert model.location == "us-central1"
        assert model.retry_options is not None
        assert model.retry_options.attempts == 5


class TestResilientHttpOptions:
    """Tests for resilient_http_options()."""

    def test_returns_http_options(self):
        from agents.utils.retry import resilient_http_options

        opts = resilient_http_options()
        assert isinstance(opts, types.HttpOptions)

    def test_retry_options_are_set(self):
        from agents.utils.retry import resilient_http_options

        opts = resilient_http_options()
        assert opts.retry_options is not None
        assert opts.retry_options.attempts == 5

    def test_api_version_passthrough(self):
        from agents.utils.retry import resilient_http_options

        opts = resilient_http_options(api_version="v1beta1")
        assert opts.api_version == "v1beta1"
        assert opts.retry_options is not None

    def test_custom_retry_options_override(self):
        from agents.utils.retry import resilient_http_options

        custom = types.HttpRetryOptions(attempts=2)
        opts = resilient_http_options(retry_options=custom)
        assert opts.retry_options is not None
        assert opts.retry_options.attempts == 2


class TestAgentIntegration:
    """Verify agents use resilient models."""

    def test_planner_uses_resilient_model(self):
        from agents.planner.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None

    def test_planner_with_eval_uses_resilient_model(self):
        from agents.planner_with_eval.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None

    def test_planner_with_memory_uses_resilient_model(self):
        from agents.planner_with_memory.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None

    def test_simulator_uses_resilient_model(self):
        from agents.simulator.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None

    def test_runner_uses_resilient_model(self):
        from agents.runner.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None

    def test_runner_autopilot_uses_resilient_model(self):
        from agents.runner_autopilot.agent import get_agent
        from agents.utils.global_gemini import GlobalGemini

        agent = get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.retry_options is not None
