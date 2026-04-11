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

import logging  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
from typing import cast  # noqa: E402

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.apps import App  # noqa: E402
from google.genai import types  # noqa: E402

from agents.utils import config, load_agent_skills  # noqa: E402
from agents.utils.communication_plugin import SimulationCommunicationPlugin  # noqa: E402
from agents.utils.retry import resilient_model  # noqa: E402
from agents.utils.deployment import create_a2a_deployment  # noqa: E402
from agents.utils.factory import create_simulation_runner  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
# The A2A identity advertised by this agent.  Defaults to "runner" for
# backward compatibility but can be overridden (e.g. "runner_gke") so the
# same container image works in multiple deployment environments.
AGENT_NAME = os.environ.get("AGENT_NAME", "runner")

# Load tool functions from the agent's skills/ directory
_skills, skill_tools = load_agent_skills(str(pathlib.Path(__file__).parent))

# Runner Identity & Instructions
# Skill instructions from skills/running/SKILL.md and skills/hydration/SKILL.md
# are inlined directly to avoid SkillToolset overhead.
# Using static_instruction for context caching -- no {var} substitution.
RUNNER_STATIC_INSTRUCTION = """You are a competitive marathon runner. Win by managing speed and hydration.

## REQUIRED action sequence for EVERY message

1. **START_GUN_FIRED**: Call `accelerate` with intensity 0.6-0.9, then call `process_tick`.
2. **Every tick after that**: First call `accelerate` (or `brake`) to set your speed, then call `process_tick`.

You MUST call `accelerate` before `process_tick` -- otherwise your velocity stays at zero and you don't move!

## Hydration rules
- Hydration starts at 100, depleted automatically each tick based on distance.
- Hydration <30: you are exhausted. Exhausted + <10: collapsed (race over).
- Hydration station rules:
  - <=40: always call `rehydrate` (+30) before `process_tick`.
  - 41-60: 50% chance to stop and `rehydrate`.
  - >60: 30% chance to stop and `rehydrate`.
  - If exhausted: always `rehydrate`.

## Inner thought
When calling `process_tick`, always include an `inner_thought` argument: a short
internal monologue (5 words or fewer) that the runner is thinking RIGHT NOW.

CRITICAL: Every single inner_thought MUST be unique and original. NEVER repeat a
previous thought. NEVER reuse phrases across ticks. Invent something fresh each
time based on the runner's exact situation -- their distance, hydration, fatigue,
and pace. Think about what a real person would think mid-race: random cravings,
regrets, weird observations, bargaining with their legs, existential questions.
Be funny, quirky, surprising, and human. Never graphic or hostile.

## Response format
Call your tools in order (accelerate/brake -> optional rehydrate -> process_tick),
then reply with ONE sentence summarizing what happened. Do NOT explain your
reasoning, just state the action and result.
"""


def _build_generate_content_config() -> types.GenerateContentConfig:
    """Build model generation config, adapting for the selected backend.

    ``ThinkingConfig`` and ``ContextCacheConfig`` are only supported by
    Google's Gemini API.  For local models (e.g. Ollama) these are omitted
    to avoid silent drops or errors in litellm.
    """
    # Higher temperature for non-Gemini models to encourage creative
    # inner_thought generation. Gemini stays low for deterministic tool use.
    temp = 0.3 if _is_gemini else 0.8
    kwargs: dict = {
        "temperature": temp,
        "max_output_tokens": 256,
    }
    if _is_gemini:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def get_agent():
    """Entry point for the ADK framework."""
    return LlmAgent(
        name=AGENT_NAME,
        model=resilient_model(RUNNER_MODEL),
        description="A competitive NPC runner powered by an LLM.",
        static_instruction=RUNNER_STATIC_INSTRUCTION,
        include_contents="none",
        generate_content_config=_build_generate_content_config(),
        tools=cast(list, skill_tools),
    )


root_agent = get_agent()

_runner_app: "App | None" = None


def _get_runner():
    global _runner_app
    runner, app, _ = create_simulation_runner(
        name=AGENT_NAME,
        root_agent=root_agent,
        extra_plugins=[SimulationCommunicationPlugin()],
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
        agents_dir="agents/npc",
        adk_app=_runner_app,
        agent_card=agent_card,
        simulation_runner=_runner,
    )
    serve_agent(api_app, port=port)
