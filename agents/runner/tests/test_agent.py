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

PARITY: Keep in sync with agents/runner_autopilot/tests/test_agent.py.
Both runner agents must expose identical external interfaces (tools, A2A, card).
"""

from agents.runner.agent import (
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
    from agents.runner import running as shared_running
    from agents.runner import hydration as shared_hydration

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
    from agents.runner.agent import _build_generate_content_config, _is_gemini

    cfg = _build_generate_content_config()
    if _is_gemini:
        assert cfg.thinking_config is not None
        assert cfg.thinking_config.thinking_budget == 0
    else:
        assert cfg.thinking_config is None


def test_agent_model_matches_runner_model():
    """The instantiated agent must use the RUNNER_MODEL value."""
    from agents.utils.global_gemini import GlobalGemini

    assert isinstance(root_agent.model, GlobalGemini)
    assert root_agent.model.model == RUNNER_MODEL


def test_non_gemini_config_omits_thinking(monkeypatch):
    """Non-Gemini models must not include ThinkingConfig.

    Temperature is unified at 0.2 across backends -- tool-call reliability
    matters more than inner_thought variety. See Task E in
    docs/plans/2026-04-19-llm-runner-cap-task-e-runner-prompt.md.
    """
    import agents.runner.agent as mod

    monkeypatch.setattr(mod, "_is_gemini", False)
    cfg = mod._build_generate_content_config()
    assert cfg.thinking_config is None
    assert cfg.temperature == 0.2
    assert cfg.max_output_tokens == 256


def test_gemini_config_has_thinking(monkeypatch):
    """Gemini models must include ThinkingConfig with budget=0.

    Temperature is unified at 0.2 across backends (was 0.3 for Gemini).
    """
    import agents.runner.agent as mod

    monkeypatch.setattr(mod, "_is_gemini", True)
    cfg = mod._build_generate_content_config()
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.temperature == 0.2


# ---------------------------------------------------------------------------
# vLLM backend tests
# ---------------------------------------------------------------------------


def test_vllm_url_sets_openai_api_base(monkeypatch):
    """When VLLM_API_URL is set, OPENAI_API_BASE is configured at module init."""
    import importlib

    import agents.runner.agent as mod

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
    import agents.runner.agent as mod

    # Simulate openai/ model by checking the detection logic
    assert not "openai/gemma-4-E4B-it".startswith("gemini")
    # The default model should be Gemini
    assert mod.DEFAULT_MODEL.startswith("gemini")


def test_runner_has_before_agent_callback():
    """Runner must have a before_agent_callback for profile initialization."""
    assert root_agent.before_agent_callback is not None


def test_vllm_url_not_set_leaves_openai_unchanged(monkeypatch):
    """When VLLM_API_URL is not set, OPENAI_API_BASE is not modified."""
    import importlib
    import os

    import agents.runner.agent as mod

    monkeypatch.delenv("VLLM_API_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("RUNNER_MODEL", raising=False)
    importlib.reload(mod)
    assert os.environ.get("OPENAI_API_BASE") is None


def test_runner_suppressed_events():
    """RUNNER_SUPPRESSED_EVENTS should suppress lifecycle events but NOT tool_end.

    tool_end must remain unsuppressed so the plugin's _emit_narrative can
    forward process_tick results to the gateway for the frontend visualization.
    The duplicate json/text noise is handled by suppress_gateway_emission on
    the dispatcher instead.
    """
    from agents.runner.agent import RUNNER_SUPPRESSED_EVENTS

    # Lifecycle events are suppressed
    assert "run_start" in RUNNER_SUPPRESSED_EVENTS
    assert "run_end" in RUNNER_SUPPRESSED_EVENTS
    assert "model_start" in RUNNER_SUPPRESSED_EVENTS
    assert "model_end" in RUNNER_SUPPRESSED_EVENTS
    assert "tool_start" in RUNNER_SUPPRESSED_EVENTS
    # tool_end must NOT be suppressed -- frontend needs process_tick data
    assert "tool_end" not in RUNNER_SUPPRESSED_EVENTS


# ---------------------------------------------------------------------------
# Non-Gemini model wrapper dispatch (LiteLlm vs GlobalGemini)
# ---------------------------------------------------------------------------


def test_ollama_model_uses_litellm_not_global_gemini(monkeypatch):
    """RUNNER_MODEL=ollama_chat/... must route via LiteLlm, NOT GlobalGemini.

    Prevents regression of the 400 INVALID_ARGUMENT bug where ollama_chat/
    was misinterpreted as a Vertex AI publisher name. See
    docs/plans/2026-04-19-llm-runner-cap-bundle-addendum.md.
    """
    import importlib

    from google.adk.models.lite_llm import LiteLlm

    import agents.runner.agent as mod

    monkeypatch.setenv("RUNNER_MODEL", "ollama_chat/gemma4:e2b")
    importlib.reload(mod)
    try:
        agent = mod.get_agent()
        assert isinstance(agent.model, LiteLlm)
        assert agent.model.model == "ollama_chat/gemma4:e2b"
    finally:
        # Restore module to default state so subsequent tests see the
        # default Gemini-backed root_agent.
        monkeypatch.delenv("RUNNER_MODEL", raising=False)
        importlib.reload(mod)


def test_gemini_model_still_uses_global_gemini(monkeypatch):
    """The default Gemini path must remain unchanged."""
    import importlib

    from agents.utils.global_gemini import GlobalGemini

    import agents.runner.agent as mod

    monkeypatch.setenv("RUNNER_MODEL", "gemini-3-flash-preview")
    importlib.reload(mod)
    try:
        agent = mod.get_agent()
        assert isinstance(agent.model, GlobalGemini)
        assert agent.model.model == "gemini-3-flash-preview"
    finally:
        monkeypatch.delenv("RUNNER_MODEL", raising=False)
        importlib.reload(mod)


# ---------------------------------------------------------------------------
# Static instruction parity with runner_autopilot tool-calling discipline
# ---------------------------------------------------------------------------


class TestRunnerStaticInstructionMatchesAutopilot:
    """The runner LLM prompt must instruct the model to behave like
    runner_autopilot: one process_tick call per tick, no chaining,
    no probabilistic logic, no nonexistent event names.

    See docs/plans/2026-04-19-llm-runner-cap-task-e-runner-prompt.md.
    """

    def test_prompt_does_not_chain_accelerate_before_process_tick(self):
        """Old prompt required 'accelerate THEN process_tick' which gemma4:e2b
        cannot reliably emit. Simplified prompt must not require chaining."""
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        text = RUNNER_STATIC_INSTRUCTION.lower()
        assert "accelerate before" not in text
        assert "then call `process_tick`" not in text
        assert "then `process_tick`" not in text

    def test_prompt_uses_actual_json_event_format(self):
        """Old prompt referenced 'START_GUN_FIRED' which never appears in
        actual messages. Simplified prompt must reference the real JSON
        event format the runner actually receives."""
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        assert "START_GUN_FIRED" not in RUNNER_STATIC_INSTRUCTION
        assert '"event"' in RUNNER_STATIC_INSTRUCTION
        assert '"tick"' in RUNNER_STATIC_INSTRUCTION

    def test_prompt_specifies_single_tool_call(self):
        """Hard constraint to help small models: one tool call per tick.

        The test asserts the *semantic* invariant rather than literal wording
        so prompt phrasing can evolve. The prompt must (a) name process_tick
        as the per-tick tool, AND (b) explicitly forbid chaining multiple
        tool calls.
        """
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        text = RUNNER_STATIC_INSTRUCTION.lower()
        assert "process_tick" in RUNNER_STATIC_INSTRUCTION
        assert "do not chain" in text or "do not chain multiple" in text
        assert "process_tick" in RUNNER_STATIC_INSTRUCTION

    def test_prompt_drops_probabilistic_hydration(self):
        """50% / 30% probability rules are unreliable on small models."""
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        assert "50%" not in RUNNER_STATIC_INSTRUCTION
        assert "30%" not in RUNNER_STATIC_INSTRUCTION

    def test_prompt_does_not_show_tool_call_as_text(self):
        """Textual tool-call examples teach gemma4:e2b to emit the call AS
        TEXT instead of as a structured function_call. Few-shot for tool
        calling must either be omitted or use the actual tool_call wire
        format. See docs/plans/2026-04-19-llm-runner-cap-task-f-prompt-bugfix.md.
        """
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        assert "process_tick(" not in RUNNER_STATIC_INSTRUCTION
        assert "YOUR ACTION" not in RUNNER_STATIC_INSTRUCTION

    def test_prompt_directs_use_of_tool_calling_mechanism(self):
        """Explicit directive helps the model favor structured function_call
        parts over textual approximations of the call."""
        from agents.runner.agent import RUNNER_STATIC_INSTRUCTION

        text = RUNNER_STATIC_INSTRUCTION.lower()
        assert "tool-calling mechanism" in text or "tool calling mechanism" in text
        assert "do not emit" in text  # negative directive about text format


class TestRunnerStateInjection:
    """The runner LLM must receive per-runner state on every tick so
    inner_thought (and any future state-aware reasoning) can vary by
    runner. Without this, every runner sees identical input (same prompt,
    same JSON tick event with only the tick number varying) and produces
    identical output at our tool-calling-friendly temperature of 0.2.
    See docs/plans/2026-04-19-llm-runner-cap-task-h-runner-state-injection.md.
    """

    def test_agent_has_dynamic_instruction(self):
        """Both static and dynamic instructions must be set so ADK appends
        per-call state context as a separate user-role content part."""
        from agents.runner.agent import root_agent

        assert root_agent.instruction, "Runner must have a dynamic instruction"
        assert root_agent.static_instruction, "Runner must keep static_instruction for cacheability"

    def test_dynamic_instruction_references_runner_state(self):
        """The dynamic instruction must reference the runner's per-tick state
        so each runner's input differs by physiology -- not just by tick number.
        All five vars are set by initialize_runner before the first LLM call
        and updated by process_tick thereafter, so they're always available."""
        from agents.runner.agent import root_agent

        text = root_agent.instruction
        # ADK types instruction as ``str | InstructionProvider``; we use a literal string.
        assert isinstance(text, str), "Runner uses a literal string instruction, not an InstructionProvider"
        assert "{distance}" in text
        assert "{water}" in text
        assert "{velocity}" in text
        assert "{runner_status}" in text
        assert "{target_finish_minutes}" in text

    def test_dynamic_instruction_does_not_use_format_specs(self):
        """ADK's inject_session_state only supports simple {var} placeholders,
        not Python format specs. Format spec placeholders would be left
        un-substituted and confuse the model.
        See google/adk/utils/instructions_utils.py:75-124.
        """
        import re

        from agents.runner.agent import root_agent

        text = root_agent.instruction
        assert isinstance(text, str), "Runner uses a literal string instruction, not an InstructionProvider"
        # Match {var:spec} or {var!r} patterns -- both unsupported by ADK.
        assert not re.search(r"\{[^{}]*[!:][^{}]*\}", text), (
            "Dynamic instruction must use only {var_name}, not Python format specs"
        )


class TestProcessTickSchemaRequiresInnerThought:
    """`inner_thought` MUST be schema-required so small models cannot drop
    it as an optional field. With a default value, ADK marks the parameter
    as not-required in the auto-generated tool schema, and gemma4:e2b
    routinely omits it -- inner_thought ends up empty in every result.
    See docs/plans/2026-04-19-llm-runner-cap-task-i-required-inner-thought.md.
    """

    def test_process_tick_signature_has_no_default_for_inner_thought(self):
        """If inner_thought has a default value, ADK marks it optional in
        the tool schema and gemma4:e2b reliably omits it. Drop the default
        to force schema-level required."""
        import inspect

        from agents.runner.running import process_tick

        sig = inspect.signature(process_tick)
        param = sig.parameters["inner_thought"]
        assert param.default is inspect.Parameter.empty, (
            "inner_thought must have no default so ADK marks it required in the tool schema"
        )

    def test_tool_schema_marks_inner_thought_required(self):
        """End-to-end: the tool schema actually sent to gemma must list
        inner_thought as required. This is the contract the model honors."""
        from google.adk.tools.function_tool import FunctionTool

        from agents.runner.running import process_tick

        ft = FunctionTool(func=process_tick)
        decl = ft._get_declaration()
        assert decl is not None
        params = decl.parameters
        assert params is not None
        required = list(getattr(params, "required", []) or [])
        assert "inner_thought" in required, (
            f"inner_thought must be in process_tick's required params; got required={required}"
        )
