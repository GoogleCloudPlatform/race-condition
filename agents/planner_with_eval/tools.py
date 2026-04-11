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

"""Planner-with-eval specific tools — simulator collaboration."""

import json
import logging
from uuid import uuid4

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


async def start_simulation(
    action: str,
    message: str,
    tool_context: ToolContext,
    simulation_config: dict | None = None,
) -> dict:
    """Initialize a simulation session and return the simulation_id.

    This tool returns immediately, making the simulation_id visible in the
    telemetry dashboard (via the DashLogPlugin tool_end callback) BEFORE
    the simulation actually begins.

    Call this BEFORE submit_plan_to_simulator(action="execute").

    Args:
        action: Either 'verify' or 'execute'.
        message: A narrative summary of the plan for the simulator.
        tool_context: ADK tool context.
        simulation_config: Optional simulation config dict.
    """
    route_geojson = tool_context.state.get("marathon_route")
    if not route_geojson:
        return {
            "status": "error",
            "message": "No marathon route found in session state. Run 'plan_marathon_route' first.",
        }

    # Generate or reuse the simulator session ID.
    simulator_session_id = tool_context.state.get("simulator_session_id")
    if not simulator_session_id:
        simulator_session_id = str(uuid4())
        tool_context.state["simulator_session_id"] = simulator_session_id

    # Set simulation_id in planner state so all subsequent messages carry it.
    tool_context.state["simulation_id"] = simulator_session_id

    # Persist simulation_config so submit_plan_to_simulator can read it
    # from state when the LLM omits it (the "carry forward" contract).
    if simulation_config:
        tool_context.state["simulation_config"] = simulation_config

    logger.info(f"PLANNER: Simulation initialized (simulation_id={simulator_session_id}, action={action})")

    return {
        "status": "ready",
        "simulation_id": simulator_session_id,
        "action": action,
        "message": f"Simulation session initialized. Call submit_plan_to_simulator to {action}.",
    }


async def submit_plan_to_simulator(
    action: str,
    message: str,
    tool_context: ToolContext,
    simulation_config: dict | None = None,
) -> dict:
    """Submit the marathon plan to the simulator agent for verification or execution.

    For execute actions, call start_simulation first to initialize the session
    and make the simulation_id visible in the telemetry dashboard.

    Args:
        action: Either 'verify' or 'execute'.
        message: A narrative summary of the plan for the simulator.
        tool_context: ADK tool context.
        simulation_config: Optional config dict with keys: duration_seconds,
            tick_interval_seconds, runner_count.
    """
    from agents.utils.communication import call_agent

    logger.info(f"PLANNER: Submitting plan to simulator with action: {action}")

    route_geojson = tool_context.state.get("marathon_route")
    if not route_geojson:
        return {
            "status": "error",
            "message": "No marathon route found in session state. Run 'plan_marathon_route' first.",
        }

    # Use session ID from start_simulation, or generate for backward compat.
    simulator_session_id = tool_context.state.get("simulator_session_id")
    if not simulator_session_id:
        simulator_session_id = str(uuid4())
        tool_context.state["simulator_session_id"] = simulator_session_id

    # Set simulation_id for plugin emissions only during execute.
    # During verify, simulation_id must NOT be set — it causes the
    # frontend to receive simulator events on an unknown session,
    # triggering an unsubscribe that drops all subsequent messages
    # (including the tool_end for this tool and the A2UI card).
    if action == "execute" and not tool_context.state.get("simulation_id"):
        tool_context.state["simulation_id"] = simulator_session_id

    # Store large data in Redis side-channel (route GeoJSON, traffic
    # assessment) so the simulator can read it directly without the LLM
    # having to pass multi-KB JSON through function call arguments.
    from agents.utils.simdata import store_simulation_data

    stored = await store_simulation_data(
        simulation_id=simulator_session_id,
        route_geojson=route_geojson,
        traffic_assessment=tool_context.state.get("traffic_assessment"),
    )

    # Build the payload from this tool's own arguments.
    # Fall back to simulation_config stored by start_simulation if not
    # passed directly (the "carry forward" contract).
    effective_config = simulation_config or tool_context.state.get("simulation_config")
    payload: dict[str, object] = {
        "action": action,
        "narrative": message,
    }
    if effective_config:
        payload["simulation_config"] = effective_config
    # When Redis is unavailable, fall back to including route and traffic
    # data directly in the A2A payload so the simulator can still proceed.
    if not stored:
        logger.warning("submit_plan_to_simulator: Redis unavailable, including route in A2A payload as fallback")
        if route_geojson:
            payload["route"] = route_geojson
        ta = tool_context.state.get("traffic_assessment")
        if ta:
            payload["traffic_assessment"] = ta

    try:
        response = await call_agent(
            tool_context=tool_context,
            agent_name="simulator",
            message=json.dumps(payload),
            session_id=simulator_session_id,
        )
        return {
            "status": "success",
            "simulation_id": simulator_session_id,
            "message": f"Successfully sent plan to simulator agent: {action}",
            "simulator_response": response,
        }
    except Exception as e:
        logger.error(f"PLANNER: Failed to call simulator agent: {e}")
        return {"status": "error", "message": f"Failed to call simulator agent: {str(e)}"}
