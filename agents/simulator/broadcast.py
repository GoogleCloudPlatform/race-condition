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

"""Redis broadcast helper for the simulator agent.

Provides a single function to publish serialized RunnerEvent data to the
``simulation:broadcast`` Redis channel with the standard broadcast envelope.
"""

import asyncio
import json
import logging
import time
import uuid

from agents.utils.redis_pool import get_shared_redis_client
from agents.utils.simulation_registry import _REDIS_SESSION_PREFIX

logger = logging.getLogger(__name__)

_READINESS_POLL_INTERVAL = 0.5  # seconds between registry polls


async def wait_for_runners_ready(
    session_ids: list[str],
    simulation_id: str,
    timeout_seconds: float = 60,
) -> int:
    """Poll the simulation registry until all runner session IDs are registered.

    The dispatchers process spawn_agent events asynchronously via BLPOP and
    register each session in Redis (SETEX simreg:session:{id}) with the
    value set to the simulation_id.  This function blocks until all
    ``session_ids`` have been registered **for this specific simulation**,
    or until ``timeout_seconds`` elapses.

    Args:
        session_ids: Runner session IDs to wait for.
        simulation_id: The current simulation ID -- values must match this.
        timeout_seconds: Max seconds to wait before proceeding anyway.

    Returns the number of runners confirmed registered for this simulation.
    """
    expected = len(session_ids)
    if expected == 0:
        return 0

    r = get_shared_redis_client()
    if r is None:
        logger.warning("wait_for_runners_ready: no Redis client, skipping spawn readiness gate")
        return 0

    deadline = time.monotonic() + timeout_seconds
    registered = 0

    while time.monotonic() < deadline:
        try:
            keys = [f"{_REDIS_SESSION_PREFIX}{sid}" for sid in session_ids]
            values = await r.mget(*keys)  # type: ignore[misc]
            registered = sum(
                1
                for v in values
                if v is not None and (v == simulation_id or (isinstance(v, bytes) and v.decode() == simulation_id))
            )
        except Exception as e:
            logger.warning("wait_for_runners_ready: registry poll failed: %s", e)
            break

        if registered >= expected:
            elapsed = timeout_seconds - (deadline - time.monotonic())
            logger.info(
                "wait_for_runners_ready: all %d runners registered (%.1fs)",
                expected,
                elapsed,
            )
            return registered

        logger.info(
            "wait_for_runners_ready: %d/%d runners registered, waiting...",
            registered,
            expected,
        )
        await asyncio.sleep(_READINESS_POLL_INTERVAL)

    logger.warning(
        "wait_for_runners_ready: timeout after %.0fs — %d/%d runners registered, proceeding",
        timeout_seconds,
        registered,
        expected,
    )
    return registered


async def publish_to_runners(
    data: str,
    simulation_id: str | None = None,
    exclude_runner_ids: list[str] | None = None,
) -> None:
    """Publish a serialized event string to runners via Redis broadcast.

    Wraps ``data`` in the standard broadcast envelope and publishes to
    a Redis channel. When ``simulation_id`` is provided the channel is
    scoped to ``simulation:{simulation_id}:broadcast``; otherwise the
    legacy ``simulation:broadcast`` channel is used for backward
    compatibility.

    Args:
        data: A JSON string (typically from ``serialize_runner_event()``).
        simulation_id: Optional simulation ID for channel scoping.
        exclude_runner_ids: Optional list of runner session IDs the
            dispatcher should skip when fanning out this broadcast.
    """
    payload: dict[str, object] = {"data": data}
    if exclude_runner_ids:
        payload["exclude_runner_ids"] = exclude_runner_ids
    envelope_dict: dict[str, object] = {
        "type": "broadcast",
        "eventId": str(uuid.uuid4()),
        "payload": payload,
    }
    if simulation_id:
        envelope_dict["simulation_id"] = simulation_id
    envelope = json.dumps(envelope_dict)

    channel = f"simulation:{simulation_id}:broadcast" if simulation_id else "simulation:broadcast"

    try:
        r = get_shared_redis_client()
        if r is None:
            return
        await r.publish(channel, envelope)
    except Exception as e:
        logger.warning("publish_to_runners: Redis publish failed: %s", e)


async def publish_end_simulation(simulation_id: str) -> None:
    """Publish an end_simulation event so dispatchers remove runner sessions.

    This is called by stop_race_collector after the race completes.  Each
    dispatcher instance that owns sessions for this simulation will remove
    them from active_sessions, clean up the simulation registry, and
    unsubscribe from the scoped Redis channel.

    Args:
        simulation_id: The simulation whose runners should be cleaned up.
    """
    envelope = json.dumps(
        {
            "type": "end_simulation",
            "simulation_id": simulation_id,
            "eventId": str(uuid.uuid4()),
        }
    )
    channel = f"simulation:{simulation_id}:broadcast"
    try:
        r = get_shared_redis_client()
        if r is None:
            return
        await r.publish(channel, envelope)
        logger.info("publish_end_simulation: published to %s", channel)
    except Exception as e:
        logger.warning("publish_end_simulation: Redis publish failed: %s", e)
