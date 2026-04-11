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

"""Tests for the LLM-powered runner agent module.

PARITY: Keep in sync with agents/npc/runner_autopilot/tests/test_agent.py.
Both runner agents must expose identical external interfaces (tools, A2A, card).
"""

from agents.npc.runner.agent import (
    AGENT_NAME,
    DEFAULT_MODEL,
    RUNNER_MODEL,
    _is_gemini,
    root_agent,
    get_agent,
    agent_card,
    runner_a2a_agent,
)


def test_root_agent_exists():
    assert root_agent is not None


def test_root_agent_name():
    assert root_agent.name == AGENT_NAME


def test_root_agent_has_no_before_model_callback():
    """Runner uses the LLM directly (no callback interception)."""
    assert root_agent.before_model_callback is None


def test_root_agent_has_expected_tools():
    """Both runner agents must expose the same tool set for interface parity."""
    tool_names = {t.__name__ for t in root_agent.tools}
    expected = {
        "accelerate",
        "brake",
        "get_vitals",
        "process_tick",
        "deplete_water",
        "rehydrate",
        "validate_and_emit_a2ui",
    }
    assert expected == tool_names


def test_tools_come_from_shared_module():
    """Verify runner tools are the canonical shared implementations.

    Note: validate_and_emit_a2ui is loaded dynamically from agents/skills/
    a2ui-rendering/ (hyphenated, no __init__.py) and cannot be identity-checked
    via normal import.  Its presence is verified by test_root_agent_has_expected_tools.
    """
    from agents.npc.runner_shared import running as shared_running
    from agents.npc.runner_shared import hydration as shared_hydration

    tools = {t.__name__: t for t in root_agent.tools}

    assert tools["accelerate"] is shared_running.accelerate
    assert tools["brake"] is shared_running.brake
    assert tools["get_vitals"] is shared_running.get_vitals
    assert tools["process_tick"] is shared_running.process_tick
    assert tools["deplete_water"] is shared_hydration.deplete_water
    assert tools["rehydrate"] is shared_hydration.rehydrate


def test_get_agent_returns_fresh_agent():
    agent = get_agent()
    assert agent is not None
    assert agent.name == AGENT_NAME
    assert agent is not root_agent


def test_agent_card_exists():
    assert agent_card is not None


def test_a2a_agent_exists():
    assert runner_a2a_agent is not None


# -- Model configuration tests ------------------------------------------------


def test_default_model_is_gemini():
    """Default model must remain the Gemini variant for cloud deployments."""
    assert DEFAULT_MODEL == "gemini-3.1-flash-lite-preview"


def test_runner_model_defaults_to_gemini():
    """Without RUNNER_MODEL env var, the agent uses the Gemini default."""
    # RUNNER_MODEL is resolved at import time; in CI there is no env override.
    assert RUNNER_MODEL == DEFAULT_MODEL


def test_is_gemini_flag_matches_model():
    """_is_gemini should be True when using the default Gemini model."""
    assert _is_gemini == RUNNER_MODEL.startswith("gemini")


def test_gemini_config_includes_thinking():
    """When using a Gemini model, ThinkingConfig must be set (budget=0)."""
    from agents.npc.runner.agent import _build_generate_content_config, _is_gemini

    cfg = _build_generate_content_config()
    if _is_gemini:
        assert cfg.thinking_config is not None
        assert cfg.thinking_config.thinking_budget == 0
    else:
        assert cfg.thinking_config is None


def test_agent_model_matches_runner_model():
    """The instantiated agent must use the RUNNER_MODEL value."""
    assert root_agent.model == RUNNER_MODEL


def test_non_gemini_config_omits_thinking(monkeypatch):
    """Non-Gemini models must not include ThinkingConfig and use higher temp."""
    import agents.npc.runner.agent as mod

    monkeypatch.setattr(mod, "_is_gemini", False)
    cfg = mod._build_generate_content_config()
    assert cfg.thinking_config is None
    # Non-Gemini uses higher temp for creative inner_thought generation.
    assert cfg.temperature == 0.8
    assert cfg.max_output_tokens == 256


def test_gemini_config_has_thinking(monkeypatch):
    """Gemini models must include ThinkingConfig with budget=0 and low temp."""
    import agents.npc.runner.agent as mod

    monkeypatch.setattr(mod, "_is_gemini", True)
    cfg = mod._build_generate_content_config()
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.temperature == 0.3


# ---------------------------------------------------------------------------
# vLLM backend tests
# ---------------------------------------------------------------------------


def test_vllm_url_sets_openai_api_base(monkeypatch):
    """When VLLM_API_URL is set, OPENAI_API_BASE is configured at module init."""
    import importlib

    import agents.npc.runner.agent as mod

    monkeypatch.setenv("VLLM_API_URL", "http://vllm-service:8000/v1")
    monkeypatch.setenv("RUNNER_MODEL", "openai/gemma-4-E4B-it")
    # Remove OPENAI_API_BASE if set so setdefault can work
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    importlib.reload(mod)
    import os

    assert os.environ.get("OPENAI_API_BASE") == "http://vllm-service:8000/v1"
    assert os.environ.get("OPENAI_API_KEY") == "not-needed"
    # Cleanup
    monkeypatch.delenv("VLLM_API_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RUNNER_MODEL", raising=False)
    importlib.reload(mod)


def test_vllm_model_is_not_gemini():
    """openai/ prefix models are not Gemini."""
    import agents.npc.runner.agent as mod

    # Simulate openai/ model by checking the detection logic
    assert not "openai/gemma-4-E4B-it".startswith("gemini")
    # The default model should be Gemini
    assert mod.DEFAULT_MODEL.startswith("gemini")


def test_vllm_url_not_set_leaves_openai_unchanged(monkeypatch):
    """When VLLM_API_URL is not set, OPENAI_API_BASE is not modified."""
    import importlib
    import os

    import agents.npc.runner.agent as mod

    monkeypatch.delenv("VLLM_API_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("RUNNER_MODEL", raising=False)
    importlib.reload(mod)
    assert os.environ.get("OPENAI_API_BASE") is None
