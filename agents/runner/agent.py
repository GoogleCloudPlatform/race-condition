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

"""NPC Runner Agent -- LLM-powered competitive marathon runner simulation.

Unlike the deterministic runner_autopilot, this agent uses an LLM to interpret
simulation events and decide which tools to call. The LLM handles strategy:
when to accelerate, when to hydrate, how to respond to boosts.

The model backend is configurable via the ``RUNNER_MODEL`` environment variable:

- **Gemini** (default): ``gemini-3.1-flash-lite-preview`` via Vertex AI
- **Ollama** (local): ``ollama_chat/gemma4:e2b`` via litellm
- **vLLM** (GKE): ``openai/gemma-4-E4B-it`` via litellm + ``VLLM_API_URL``

See ``docs/guides/local-ollama-setup.md`` and ``docs/guides/gke-vllm-setup.md``
for backend-specific setup instructions.
"""

from agents.utils.env import configure_project_env

configure_project_env("runner")

import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
from typing import cast  # noqa: E402

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.adk.models.lite_llm import LiteLlm  # noqa: E402
from google.genai import types  # noqa: E402

from agents.utils import config, load_agent_skills  # noqa: E402
from agents.utils.communication_plugin import SimulationCommunicationPlugin  # noqa: E402
from agents.utils.retry import resilient_model  # noqa: E402
from agents.utils.deployment import create_a2a_deployment  # noqa: E402
from agents.utils.factory import create_simulation_runner  # noqa: E402
from agents.utils.plugins import RedisDashLogPlugin  # noqa: E402
from agents.runner.initialization import initialize_runner  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Events suppressed from the dashboard for all runner agents.
# We suppress lifecycle events (run_start/end, model_start/end, tool_start)
# but NOT tool_end -- the plugin's _emit_narrative uses tool_end to forward
# process_tick results to the gateway for the frontend race visualization.
# The dispatcher's duplicate json/text emission is handled separately via
# suppress_gateway_emission=True on the SimulationNetworkPlugin.
RUNNER_SUPPRESSED_EVENTS: frozenset[str] = frozenset(
    {
        "run_start",
        "model_start",
        "model_end",
        "tool_start",
        "run_end",
    }
)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
RUNNER_MODEL = os.environ.get("RUNNER_MODEL", DEFAULT_MODEL)

# True when the selected model is served by Google's Gemini API / Vertex AI.
_is_gemini = RUNNER_MODEL.startswith("gemini")

# vLLM backend: when VLLM_API_URL is set, configure litellm's OpenAI
# provider to route to the vLLM server instead of OpenAI's API.
# This uses ``os.environ.setdefault`` so explicit OPENAI_API_BASE takes precedence.
VLLM_API_URL = os.environ.get("VLLM_API_URL", "")
if VLLM_API_URL:
    os.environ.setdefault("OPENAI_API_BASE", VLLM_API_URL)
    os.environ.setdefault("OPENAI_API_KEY", "not-needed")

if not _is_gemini:
    logger.info("Runner using non-Gemini model: %s", RUNNER_MODEL)

# ---------------------------------------------------------------------------
# Agent name configuration
# ---------------------------------------------------------------------------
# The A2A identity advertised by this agent. Can be overridden via env var
# (e.g. "runner_gke") so the same image works in multiple environments.
AGENT_NAME = os.environ.get("AGENT_NAME", "runner")

# Load tool functions from the agent's skills/ directory
_skills, skill_tools = load_agent_skills(str(pathlib.Path(__file__).parent))

# Runner Identity & Instructions
# Skill instructions from skills/running/SKILL.md and skills/hydration/SKILL.md
# are inlined directly to avoid SkillToolset overhead.
# Using static_instruction for context caching -- no {var} substitution.
# [START runner_instruction]
RUNNER_STATIC_INSTRUCTION = """You are a competitive marathon runner. Each user message is a JSON event from
the simulator. The most common event is a tick:

  {"event":"tick","tick":<n>,"max_ticks":<n>,"minutes_per_tick":<f>,
   "elapsed_minutes":<f>,"race_distance_mi":<f>,"collector_buffer_key":<s>}

## Your job on every tick

On every tick event you MUST call `process_tick`. Always. No exceptions.
Use the tool-calling mechanism -- do NOT emit the call as text. The call
must be a structured function_call part.

`process_tick` requires ALL of these arguments. Never omit any of them:
  - `tick` (from the event)
  - `minutes_per_tick` (from the event)
  - `elapsed_minutes` (from the event)
  - `race_distance_mi` (from the event)
  - `collector_buffer_key` (from the event)
  - `inner_thought` (you write this -- a short <=5 word thought the runner
    is thinking right now, e.g. "Lungs burning, push through.",
    "Halfway there.", "Legs heavy now.", "Crowd noise helps.")

`inner_thought` is required. Never pass empty. Never omit it. Always write
something fresh, ideally referencing your current distance, water, or
status from the runner-state context message.

Do NOT call any other tool unless explicitly instructed by a non-tick
event. Do NOT chain multiple tool calls. Do NOT respond with narrative
text -- only the single structured tool call.

## Non-tick events

If the event is `{"event":"start_gun"}`: respond with the text "Ready."
If the event is anything else: respond with the text "ack".
"""
# [END runner_instruction]

# Per-call dynamic instruction: ADK substitutes {var} placeholders from
# session state via inject_session_state. This gives gemma4 (and Gemini)
# per-runner physiology so inner_thought varies by runner -- without it,
# every runner sees identical input and produces identical output at our
# tool-calling-friendly temperature of 0.2. All five referenced vars are
# set by initialize_runner on the first tick (see agents/runner/initialization.py:95-109)
# and updated by process_tick thereafter, so KeyError risk is zero.
# See docs/plans/2026-04-19-llm-runner-cap-task-h-runner-state-injection.md.
RUNNER_DYNAMIC_INSTRUCTION = (
    "Runner state right now -- "
    "distance: {distance} mi, "
    "water: {water}%, "
    "velocity: {velocity} mph, "
    "status: {runner_status}, "
    "target finish: {target_finish_minutes} min."
)


# [START runner_model_config]
def _build_generate_content_config() -> types.GenerateContentConfig:
    """Build model generation config, adapting for the selected backend.

    ``ThinkingConfig`` and ``ContextCacheConfig`` are only supported by
    Google's Gemini API.  For local models (e.g. Ollama) these are omitted
    to avoid silent drops or errors in litellm.

    Temperature is unified at 0.2 across backends. Tool-call reliability
    matters more than inner_thought variety -- small models in particular
    need a low-temperature regime to reliably emit a structured tool call
    per tick. process_tick's auto-hydration replaces any LLM-level
    creativity that previously justified the 0.8 non-Gemini temperature.
    See Task E in docs/plans/2026-04-19-llm-runner-cap-task-e-runner-prompt.md.
    """
    kwargs: dict = {
        "temperature": 0.2,
        "max_output_tokens": 256,
    }
    if _is_gemini:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


async def _runner_before_agent_callback(callback_context):
    """Initialize runner profile and extract tick params from incoming message.

    On first tick (velocity is None), initializes the runner profile.
    On every tick event, extracts simulation timing parameters into
    ``state["_tick_params"]`` so ``process_tick`` can read them from state
    instead of relying on the LLM to pass them as arguments.
    """
    state = callback_context.state

    # --- Initialize runner on first tick ---
    if state.get("velocity") is None:
        session = getattr(callback_context, "session", None)
        sid = getattr(session, "id", "unknown") if session else "unknown"
        runner_count = state.get("runner_count", 10)
        initialize_runner(state, sid, runner_count)
        logger.info(
            "Runner initialized: velocity=%.4f target_finish=%.1f min",
            state["velocity"],
            state.get("target_finish_minutes", 0),
        )

    # --- Extract tick params from user message into state ---
    content = getattr(callback_context, "user_content", None)
    if content and hasattr(content, "parts") and content.parts:
        for part in content.parts:
            text = getattr(part, "text", None)
            if not text:
                continue
            try:
                msg = json.loads(text)
                if isinstance(msg, dict) and msg.get("event") == "tick":
                    state["_tick_params"] = {
                        "tick": msg.get("tick", 0),
                        "minutes_per_tick": msg.get("minutes_per_tick", 0.0),
                        "elapsed_minutes": msg.get("elapsed_minutes", 0.0),
                        "race_distance_mi": msg.get("race_distance_mi", 26.2188),
                        "collector_buffer_key": msg.get("collector_buffer_key", ""),
                    }
                    break
            except (json.JSONDecodeError, TypeError):
                pass

    return None  # Continue to LLM


def get_agent():
    """Entry point for the ADK framework.

    Model dispatch:
      - Gemini strings (``RUNNER_MODEL`` starts with ``"gemini"``) use the
        project's :func:`resilient_model` wrapper (Vertex AI / GlobalGemini
        with retry).
      - All other strings (``ollama_chat/...``, ``openai/...``,
        vLLM-via-OpenAI, etc.) use ADK's :class:`LiteLlm` backend directly so
        litellm can route to local or self-hosted servers. Without this
        branch, ``resilient_model`` would unconditionally wrap the string in
        ``GlobalGemini`` and Vertex would 400 with
        ``Invalid Endpoint name: .../publishers/<prefix>/...``.
    """
    return LlmAgent(
        name=AGENT_NAME,
        model=resilient_model(RUNNER_MODEL) if _is_gemini else LiteLlm(model=RUNNER_MODEL),
        description="A competitive NPC runner powered by an LLM.",
        static_instruction=RUNNER_STATIC_INSTRUCTION,
        instruction=RUNNER_DYNAMIC_INSTRUCTION,
        include_contents="none",
        generate_content_config=_build_generate_content_config(),
        tools=cast(list, skill_tools),
        before_agent_callback=_runner_before_agent_callback,
    )


# [END runner_model_config]


root_agent = get_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name=AGENT_NAME,
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
        dash_log_plugin=RedisDashLogPlugin(
            fire_and_forget=True,
            suppressed_events=RUNNER_SUPPRESSED_EVENTS,
        ),
        suppress_gateway_emission=True,
    )
    _runner_app = app
    return runner


# --- A2A Deployment ---
# Context caching is a Gemini-API-only feature; skip for local models.
_cache_config = ContextCacheConfig(cache_intervals=10, ttl_seconds=1800) if _is_gemini else None
app = App(
    name=AGENT_NAME,
    root_agent=root_agent,
    context_cache_config=_cache_config,
)

runner_a2a_agent, agent_card = create_a2a_deployment(
    name=AGENT_NAME,
    app_or_agent=app,
    agent_getter=get_agent,
)

if __name__ == "__main__":
    from agents.utils.serve import create_agent_app, serve_agent

    config.load_env()
    port = int(config.optional("PORT", config.optional("RUNNER_PORT", "8207")))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Starting runner LLM agent server on port %d", port)

    _runner = _get_runner()

    api_app = create_agent_app(
        name=AGENT_NAME,
        agents_dir="agents",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
