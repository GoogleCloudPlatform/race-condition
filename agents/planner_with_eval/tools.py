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

import asyncio
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

    # Re-entrancy guard: if a simulation was already executed in the SAME
    # invocation (LLM response), reject. The invocation_id changes when a
    # new user message arrives, so legitimate re-runs are allowed.
    executed_in = tool_context.state.get("simulation_executed_invocation")
    if executed_in and executed_in == tool_context.invocation_id:
        logger.warning("start_simulation: simulation already executed in this invocation, rejecting")
        return {
            "status": "error",
            "message": "Simulation already complete. Do NOT call start_simulation or "
            "submit_plan_to_simulator again. Proceed to: "
            "record_simulation, store_simulation_summary, then validate_and_emit_a2ui.",
        }

    simulator_session_id = str(uuid4())

    # Write a unique token BEFORE setting the session ID so that
    # submit_plan_to_simulator (running concurrently) can detect
    # a fresh start_simulation vs a stale value from a prior run.
    tool_context.state["_sim_token"] = simulator_session_id
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

    # Re-entrancy guard: block duplicate execute calls within the SAME
    # invocation (LLM response). The LLM may ignore prompt STOP instructions
    # and loop, calling this tool multiple times. This code-level guard is
    # deterministic — it cannot be bypassed.
    # The invocation_id changes when a new user message arrives, so
    # legitimate user-initiated re-runs (e.g. "Re-run Simulation" button)
    # are allowed because they start a new invocation.
    executed_in = tool_context.state.get("simulation_executed_invocation")
    if action == "execute" and executed_in and executed_in == tool_context.invocation_id:
        logger.warning("submit_plan_to_simulator: simulation already executed in this invocation, rejecting duplicate")
        return {
            "status": "error",
            "message": "Simulation already complete. Do NOT call start_simulation or "
            "submit_plan_to_simulator again. Proceed to: "
            "record_simulation, store_simulation_summary, then validate_and_emit_a2ui.",
        }

    # Wait for start_simulation to write a FRESH simulator_session_id.
    # Both tools are dispatched in the same LLM response.  The state
    # may already contain a stale simulator_session_id from a prior
    # simulation on this session.  We use _sim_token (written by
    # start_simulation just before simulator_session_id) to detect
    # freshness: when _sim_token == simulator_session_id, the value
    # was written by the current start_simulation call, not a prior one.
    simulator_session_id = tool_context.state.get("simulator_session_id")
    sim_token = tool_context.state.get("_sim_token")

    # Poll until start_simulation writes a fresh value (token matches ID)
    # or until we timeout (2s).
    if not simulator_session_id or simulator_session_id != sim_token:
        for _ in range(20):  # 20 x 0.1s = 2s max
            await asyncio.sleep(0.1)
            simulator_session_id = tool_context.state.get("simulator_session_id")
            sim_token = tool_context.state.get("_sim_token")
            if simulator_session_id and simulator_session_id == sim_token:
                break
    if not simulator_session_id:
        if action == "execute":
            # The LLM skipped start_simulation. Call it ourselves so the
            # frontend receives the simulation_id through the normal channel
            # (DashLogPlugin tool_end callback).
            logger.warning("submit_plan_to_simulator: start_simulation was not called; invoking it now")
            start_result = await start_simulation(
                action=action,
                message=message,
                tool_context=tool_context,
                simulation_config=simulation_config,
            )
            simulator_session_id = start_result.get("simulation_id") or str(uuid4())
            if start_result.get("status") == "error":
                return start_result
        else:
            # For verify, just generate a session ID without setting
            # simulation_id (which would poison the frontend).
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
        # Pass simulation_id in the payload body, not just as the A2A
        # context_id.  On Agent Engine the A2A transport may assign a
        # different context_id, so the simulator must read the
        # authoritative simulation_id from the payload.
        "simulation_id": simulator_session_id,
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
        # Mark execution complete so subsequent LLM loops are blocked.
        # Store the invocation_id so the guard is scoped to this invocation.
        # A new user message starts a new invocation, allowing re-runs.
        if action == "execute":
            tool_context.state["simulation_executed_invocation"] = tool_context.invocation_id

        return {
            "status": "success",
            "simulation_id": simulator_session_id,
            "message": f"Successfully sent plan to simulator agent: {action}",
            "simulator_response": response,
        }
    except Exception as e:
        logger.error(f"PLANNER: Failed to call simulator agent: {e}")
        return {"status": "error", "message": f"Failed to call simulator agent: {str(e)}"}
