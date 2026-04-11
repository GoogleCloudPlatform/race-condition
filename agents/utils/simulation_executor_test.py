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

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.types import TextPart
from agents.utils.simulation_executor import SimulationExecutor


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "test_agent"
    return agent


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.app_name = "test_agent"
    runner.run_async = AsyncMock()
    runner.session_service = AsyncMock()
    return runner


@pytest.fixture
def executor(mock_agent):
    return SimulationExecutor(
        agent_getter=lambda: mock_agent,
        agent_name="test_agent",
    )


def test_dispatch_mode_cached_at_init():
    """dispatch_mode should be read from env at construction time."""
    with patch.dict(os.environ, {"DISPATCH_MODE": "callable"}):
        ex = SimulationExecutor(agent_getter=lambda: MagicMock(), agent_name="t")
    assert ex._dispatch_mode == "callable"


def test_dispatch_mode_defaults_to_subscriber():
    """dispatch_mode should default to 'subscriber' when env var is absent."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DISPATCH_MODE", None)
        ex = SimulationExecutor(agent_getter=lambda: MagicMock(), agent_name="t")
    assert ex._dispatch_mode == "subscriber"


def test_dispatch_mode_not_affected_by_later_env_change():
    """Cached dispatch_mode is not affected by env changes after construction."""
    with patch.dict(os.environ, {"DISPATCH_MODE": "callable"}):
        ex = SimulationExecutor(agent_getter=lambda: MagicMock(), agent_name="t")
    # Env change after construction should NOT affect cached value
    with patch.dict(os.environ, {"DISPATCH_MODE": "subscriber"}):
        assert ex._dispatch_mode == "callable"


@pytest.mark.asyncio
async def test_execute_orchestration_event(executor, mock_runner):
    """Verify that JSON orchestration events are intercepted and handled."""
    # Mock runner and session manager
    executor._runner = mock_runner
    mock_session_manager = AsyncMock()
    executor._session_manager = mock_session_manager

    # Mock context and event queue
    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.task_id = "test-task"

    # Create an orchestration event as user input
    orchestration_event = {
        "type": "broadcast",
        "eventId": "evt-123",
        "sessionId": "test-session",
        "payload": {"data": "PULSE"},
    }
    context.get_user_input.return_value = json.dumps(orchestration_event)

    event_queue = MagicMock()

    # Mock the plugin and its dispatcher
    mock_plugin = MagicMock()
    mock_plugin.dispatcher = AsyncMock()

    # We'll patch where it's USED in the execute method
    # and we need to patch the class itself since we use isinstance()
    with patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater:
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.update_status = AsyncMock()
        mock_updater_inst.complete = AsyncMock()

        # Manually set up the plugin on the runner's app
        from agents.utils.simulation_plugin import SimulationNetworkPlugin

        mock_runner.app.plugins = [mock_plugin]

        # Ensure isinstance(mock_plugin, SimulationNetworkPlugin) is true
        # or just make mock_plugin an instance of the class
        with patch(
            "agents.utils.simulation_executor.isinstance",
            side_effect=lambda obj, cls: True if cls == SimulationNetworkPlugin else isinstance(obj, cls),
        ):
            await executor.execute(context, event_queue)

    # Verify dispatcher was called with the parsed event
    mock_plugin.dispatcher.handle_event.assert_called_once_with(orchestration_event)

    # Verify runner.run_async WAS NOT called (since it's a pulse)
    mock_runner.run_async.assert_not_called()


@pytest.mark.asyncio
async def test_execute_normal_query(executor, mock_runner):
    """Verify that normal text queries proceed to LLM execution."""
    executor._runner = mock_runner
    mock_session_manager = AsyncMock()
    executor._session_manager = mock_session_manager
    mock_session_manager.get_or_create_session.return_value = "internal-sid-123"

    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.get_user_input.return_value = "Hello agent"

    event_queue = MagicMock()

    # Mock runner results
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.content.parts = [TextPart(text="Hello world")]

    async def mock_run(*args, **kwargs):
        yield mock_event

    mock_runner.run_async.side_effect = mock_run

    with patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater:
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.update_status = AsyncMock()
        mock_updater_inst.complete = AsyncMock()
        mock_updater_inst.add_artifact = AsyncMock()

        # Execute
        await executor.execute(context, event_queue)

    # Verify runner was called
    mock_runner.run_async.assert_called_once()
    assert "internal-sid-123" == mock_runner.run_async.call_args.kwargs["session_id"]


@pytest.mark.asyncio
async def test_execute_callable_spawn_acknowledged(executor, mock_runner):
    """Callable mode: spawn_agent should acknowledge without dispatcher."""
    executor._runner = mock_runner
    executor._session_manager = AsyncMock()
    executor._dispatch_mode = "callable"

    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.task_id = "test-task"

    spawn_event = {
        "type": "spawn_agent",
        "sessionId": "test-session",
        "payload": {"agentType": "test_agent"},
    }
    context.get_user_input.return_value = json.dumps(spawn_event)

    event_queue = MagicMock()

    with patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater:
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.complete = AsyncMock()

        await executor.execute(context, event_queue)

    mock_updater_inst.complete.assert_called_once()
    mock_runner.run_async.assert_not_called()


@pytest.mark.asyncio
async def test_execute_callable_broadcast_runs_agent(executor, mock_runner):
    """Callable mode: broadcast should extract text and run via direct path."""
    executor._runner = mock_runner
    executor._dispatch_mode = "callable"
    mock_session_manager = AsyncMock()
    executor._session_manager = mock_session_manager
    mock_session_manager.get_or_create_session.return_value = "vertex-sid-1"

    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.task_id = "test-task"

    broadcast_event = {
        "type": "broadcast",
        "payload": {
            "data": '{"text": "What is your role?"}',
            "targets": ["test-session"],
        },
    }
    context.get_user_input.return_value = json.dumps(broadcast_event)

    event_queue = MagicMock()

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.author = "agent"
    mock_event.content.parts = [TextPart(text="I am the agent")]

    async def mock_run(*args, **kwargs):
        yield mock_event

    mock_runner.run_async.side_effect = mock_run

    with (
        patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater,
        patch("agents.utils.simulation_executor.pulses") as mock_pulses,
    ):
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.update_status = AsyncMock()
        mock_updater_inst.complete = AsyncMock()
        mock_updater_inst.add_artifact = AsyncMock()
        mock_pulses.emit_gateway_message = AsyncMock()

        await executor.execute(context, event_queue)

    # Agent should have been called with the extracted text (not the full JSON)
    mock_runner.run_async.assert_called_once()
    call_kwargs = mock_runner.run_async.call_args.kwargs
    assert call_kwargs["session_id"] == "vertex-sid-1"
    assert call_kwargs["new_message"].parts[0].text == "What is your role?"


@pytest.mark.asyncio
async def test_execute_callable_broadcast_empty_text_skipped(executor, mock_runner):
    """Callable mode: broadcast with empty text should be skipped."""
    executor._runner = mock_runner
    executor._session_manager = AsyncMock()
    executor._dispatch_mode = "callable"

    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.task_id = "test-task"

    broadcast_event = {
        "type": "broadcast",
        "payload": {
            "data": "",
            "targets": ["test-session"],
        },
    }
    context.get_user_input.return_value = json.dumps(broadcast_event)

    event_queue = MagicMock()

    with patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater:
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.complete = AsyncMock()

        await executor.execute(context, event_queue)

    mock_updater_inst.complete.assert_called_once()
    mock_runner.run_async.assert_not_called()


@pytest.mark.asyncio
async def test_execute_callable_broadcast_plain_string_data(executor, mock_runner):
    """Callable mode: broadcast with non-JSON data should use raw string."""
    executor._runner = mock_runner
    executor._dispatch_mode = "callable"
    mock_session_manager = AsyncMock()
    executor._session_manager = mock_session_manager
    mock_session_manager.get_or_create_session.return_value = "vertex-sid-2"

    context = MagicMock(spec=RequestContext)
    context.context_id = "test-session"
    context.task_id = "test-task"

    # data is a plain string, not JSON — exercises JSONDecodeError fallback
    broadcast_event = {
        "type": "broadcast",
        "payload": {
            "data": "plain text instruction",
            "targets": ["test-session"],
        },
    }
    context.get_user_input.return_value = json.dumps(broadcast_event)

    event_queue = MagicMock()

    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_event.author = "agent"
    mock_event.content.parts = [TextPart(text="Acknowledged")]

    async def mock_run(*args, **kwargs):
        yield mock_event

    mock_runner.run_async.side_effect = mock_run

    with (
        patch("agents.utils.simulation_executor.TaskUpdater") as MockUpdater,
        patch("agents.utils.simulation_executor.pulses") as mock_pulses,
    ):
        mock_updater_inst = MockUpdater.return_value
        mock_updater_inst.submit = AsyncMock()
        mock_updater_inst.start_work = AsyncMock()
        mock_updater_inst.update_status = AsyncMock()
        mock_updater_inst.complete = AsyncMock()
        mock_updater_inst.add_artifact = AsyncMock()
        mock_pulses.emit_gateway_message = AsyncMock()

        await executor.execute(context, event_queue)

    # Agent should have been called with the raw string (not parsed JSON)
    mock_runner.run_async.assert_called_once()
    call_kwargs = mock_runner.run_async.call_args.kwargs
    assert call_kwargs["new_message"].parts[0].text == "plain text instruction"


@pytest.mark.asyncio
async def test_init_runner_configures_logging(executor):
    """_init_runner should configure basicConfig if no handlers exist."""
    import logging as logging_mod

    with (
        patch("agents.utils.simulation_executor.create_services") as mock_svc,
        patch("agents.utils.simulation_executor.Runner"),
        patch("agents.utils.plugins.RedisDashLogPlugin"),
        patch("agents.utils.simulation_plugin.SimulationNetworkPlugin"),
        patch("google.adk.apps.App"),
        patch("agents.utils.simulation_executor.logging") as mock_logging,
    ):
        mock_svc.return_value = MagicMock()

        # Simulate no handlers on root logger (Agent Engine environment)
        mock_root = MagicMock()
        mock_root.handlers = []
        mock_logging.getLogger.return_value = mock_root
        mock_logging.INFO = logging_mod.INFO

        executor._init_runner()

        mock_logging.basicConfig.assert_called_once_with(
            level=logging_mod.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )


@pytest.mark.asyncio
async def test_init_runner_skips_logging_when_handlers_exist(executor):
    """_init_runner should NOT call basicConfig if handlers already exist."""
    with (
        patch("agents.utils.simulation_executor.create_services") as mock_svc,
        patch("agents.utils.simulation_executor.Runner"),
        patch("agents.utils.plugins.RedisDashLogPlugin"),
        patch("agents.utils.simulation_plugin.SimulationNetworkPlugin"),
        patch("google.adk.apps.App"),
        patch("agents.utils.simulation_executor.logging") as mock_logging,
    ):
        mock_svc.return_value = MagicMock()

        # Simulate handlers already present (normal environment)
        mock_root = MagicMock()
        mock_root.handlers = [MagicMock()]
        mock_logging.getLogger.return_value = mock_root

        executor._init_runner()

        mock_logging.basicConfig.assert_not_called()
