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

"""Tests that local A2A serving uses SimulationExecutor.

This is a regression test for the simulation ID mismatch bug where the
local serving path (register_a2a_routes) used ADK's built-in
A2aAgentExecutor instead of our SimulationExecutor.  The built-in
executor does not map context_id → simulation_id, so DashLogPlugin
emitted events with the wrong session ID and the frontend never
received them.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService

from agents.utils.simulation_executor import SimulationExecutor


def _make_agent_card(name="test_agent"):
    """Create a minimal AgentCard for testing."""
    from a2a.types import AgentSkill
    from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card

    return create_agent_card(
        agent_name=name,
        description="Test agent",
        skills=[
            AgentSkill(
                id="test",
                name="Test",
                description="A test skill",
                tags=["test"],
            )
        ],
    )


def test_register_a2a_routes_uses_simulation_executor():
    """register_a2a_routes must use SimulationExecutor, not A2aAgentExecutor.

    This is the core regression test for the simulation ID mismatch.
    If this test fails, events emitted by local agents will not carry
    the correct simulation_id and the frontend will not receive them.
    """
    from agents.utils.a2a import register_a2a_routes

    app = FastAPI()
    agent = Agent(name="test_agent", model="gemini-3-flash-preview")
    adk_app = App(name="test_agent", root_agent=agent)
    runner = Runner(app=adk_app, session_service=InMemorySessionService())
    card = _make_agent_card("test_agent")

    # Capture the executor that gets passed to DefaultRequestHandler
    captured_executor = {}

    original_drh = None
    import a2a.server.request_handlers as rh_mod

    original_drh = rh_mod.DefaultRequestHandler

    def capture_handler(*args, **kwargs):
        captured_executor["instance"] = kwargs.get("agent_executor") or (args[0] if args else None)
        return original_drh(*args, **kwargs)

    with patch(
        "agents.utils.a2a.DefaultRequestHandler",
        side_effect=capture_handler,
    ):
        register_a2a_routes(
            app,
            adk_app,
            card,
            path_prefix="/a2a/test_agent",
            simulation_runner=runner,
        )

    executor = captured_executor.get("instance")
    assert executor is not None, "DefaultRequestHandler was not called"
    assert isinstance(executor, SimulationExecutor), (
        f"Expected SimulationExecutor, got {type(executor).__name__}. "
        f"This means local serving will not map simulation IDs correctly."
    )


def test_register_a2a_routes_executor_has_runner():
    """SimulationExecutor created by register_a2a_routes must have the runner pre-wired."""
    from agents.utils.a2a import register_a2a_routes

    app = FastAPI()
    agent = Agent(name="test_agent", model="gemini-3-flash-preview")
    adk_app = App(name="test_agent", root_agent=agent)
    runner = Runner(app=adk_app, session_service=InMemorySessionService())
    card = _make_agent_card("test_agent")

    captured = {}

    import a2a.server.request_handlers as rh_mod

    original_drh = rh_mod.DefaultRequestHandler

    def capture_handler(*args, **kwargs):
        captured["executor"] = kwargs.get("agent_executor") or (args[0] if args else None)
        return original_drh(*args, **kwargs)

    with patch(
        "agents.utils.a2a.DefaultRequestHandler",
        side_effect=capture_handler,
    ):
        register_a2a_routes(
            app,
            adk_app,
            card,
            path_prefix="/a2a/test_agent",
            simulation_runner=runner,
        )

    executor = captured["executor"]
    assert isinstance(executor, SimulationExecutor)
    # The executor must have the runner pre-wired (not lazy-init)
    assert executor._runner is runner, (
        "SimulationExecutor must use the provided runner, not create its own. "
        "Without the same runner, the executor's session service won't match "
        "the one used by the agent's plugins."
    )
    assert executor._session_manager is not None, (
        "SimulationExecutor must have a SessionManager when runner is provided"
    )


def test_simulation_executor_external_runner_skips_lazy_init():
    """SimulationExecutor with external runner should skip _init_runner."""
    agent = Agent(name="test", model="gemini-3-flash-preview")
    adk_app = App(name="test", root_agent=agent)
    session_svc = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_svc)

    executor = SimulationExecutor(
        agent_name="test",
        runner=runner,
    )

    # Runner should be set immediately (not None)
    assert executor._runner is runner
    assert executor._session_manager is not None

    # Calling _init_runner should be a no-op (runner already set)
    executor._init_runner()
    assert executor._runner is runner, "_init_runner should not replace the runner"


def test_simulation_executor_no_runner_defers_init():
    """SimulationExecutor without runner should defer to _init_runner."""
    executor = SimulationExecutor(
        agent_getter=lambda: MagicMock(),
        agent_name="deferred",
    )

    assert executor._runner is None
    assert executor._session_manager is None
