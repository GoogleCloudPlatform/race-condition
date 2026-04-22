# Copyright 2026 Google LLC
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Any, Dict, List

from agents.utils import redis_pool
from gen_proto.gateway import gateway_pb2

logger = logging.getLogger(__name__)

_NUM_PUBLISH_WORKERS = 16
_publish_queue: asyncio.Queue[bytes] | None = None
_worker_tasks: list[asyncio.Task[None]] = []


def _get_queue() -> asyncio.Queue[bytes]:
    """Lazy-init the publish queue in the current event loop."""
    global _publish_queue
    if _publish_queue is None:
        _publish_queue = asyncio.Queue(maxsize=10000)
    return _publish_queue


def reset() -> None:
    """Reset publish state. Call between test cases or on shutdown.

    Note: cancel() only *requests* cancellation; we don't await the tasks.
    This is safe because cancelled tasks raise CancelledError on their next
    await (the queue.get() call), and the new queue created by _get_queue()
    is a separate object they'll never reference.
    """
    global _publish_queue
    for task in _worker_tasks:
        task.cancel()
    _worker_tasks.clear()
    _publish_queue = None


def _get_redis_client():
    return redis_pool.get_shared_redis_client()


async def _publish_worker() -> None:
    """Background task: drain queue, pipeline publishes to Redis."""
    while True:
        # Block for at least one item
        queue = _get_queue()
        batch: list[bytes] = [await queue.get()]
        # Drain any additional ready items (up to 100)
        while not queue.empty() and len(batch) < 100:
            batch.append(queue.get_nowait())

        r = _get_redis_client()
        if r is None:
            logger.warning(
                "GATEWAY_BATCH_ERROR: Redis client unavailable, dropping %d messages",
                len(batch),
            )
            continue
        try:
            async with r.pipeline(transaction=False) as pipe:
                for msg in batch:
                    pipe.publish("gateway:broadcast", msg)
                t_pub_start = time.perf_counter()
                await pipe.execute()
                t_pub_end = time.perf_counter()
                logger.info(
                    "PERF_TRACE: batch_published count=%d elapsed_ms=%.1f",
                    len(batch),
                    (t_pub_end - t_pub_start) * 1000,
                )
        except Exception as e:
            logger.warning(
                "GATEWAY_BATCH_ERROR: Pipeline publish failed (%d msgs dropped): %s",
                len(batch),
                e,
            )


async def _ensure_worker() -> None:
    """Start the publish worker pool if not already running."""
    global _worker_tasks
    # Remove dead tasks
    _worker_tasks = [t for t in _worker_tasks if not t.done()]
    # Start missing workers
    loop = asyncio.get_running_loop()
    while len(_worker_tasks) < _NUM_PUBLISH_WORKERS:
        task = loop.create_task(_publish_worker())
        _worker_tasks.append(task)


async def _publish_to_gateway(wrapper_bytes: bytes) -> None:
    await _ensure_worker()
    try:
        _get_queue().put_nowait(wrapper_bytes)
    except asyncio.QueueFull:
        logger.warning("GATEWAY_EMIT_ERROR: Publish queue full, dropping message")


async def emit_gateway_message(
    origin: Dict[str, str],
    destination: List[str],
    status: str,
    msg_type: str,
    event: str,
    data: Any,
    metadata: Optional[Dict[str, Any]] = None,
    simulation_id: Optional[str] = None,
):
    """Unified function to emit standardized gateway messages."""
    try:
        # Import dynamically to avoid circular dependencies
        from agents.utils.plugins import _safe_json_dumps
    except ImportError:

        def _safe_json_dumps(obj: Any) -> str:
            return json.dumps(obj, default=str)

    origin_msg = gateway_pb2.Origin(
        type=origin.get("type", "agent"),
        id=origin.get("id", "unknown"),
        session_id=origin.get("session_id", "system"),
    )

    # Serialize payload based on data type.
    if isinstance(data, (dict, list)):
        payload_bytes = _safe_json_dumps(data).encode("utf-8")
        # Ensure json type if it's a dict/list and not overridden
        if msg_type == "text":
            msg_type = "json"
    else:
        # Pydantic models and other objects will be handled by _safe_json_dumps
        payload_str = _safe_json_dumps(data) if not isinstance(data, str) else data
        payload_bytes = payload_str.encode("utf-8")

    meta_bytes = b""
    if metadata:
        meta_bytes = _safe_json_dumps(metadata).encode("utf-8")

    wrapper = gateway_pb2.Wrapper(
        timestamp=datetime.now().isoformat(),
        type=msg_type,
        request_id=f"gw-{datetime.now().timestamp()}",
        session_id=origin_msg.session_id,  # Legacy fallback for routing
        payload=payload_bytes,
        origin=origin_msg,
        destination=destination,
        status=status,
        event=event,
        metadata=meta_bytes,
    )

    if simulation_id:
        wrapper.simulation_id = simulation_id

    await _publish_to_gateway(wrapper.SerializeToString())
    logger.debug(f"GATEWAY_MSG: [{event}] from {origin_msg.id} to {destination} ({status})")


# [START emit_narrative_pulse]
async def emit_narrative_pulse(
    session_id: str,
    text: str,
    author: Optional[str] = None,
    type: str = "text",
    metadata: Optional[dict] = None,
    simulation_id: Optional[str] = None,
):
    """Legacy wrapper for narrative pulses. Maps to emit_gateway_message."""
    await emit_gateway_message(
        origin={"type": "agent", "id": author or "system", "session_id": session_id},
        destination=[session_id],  # Session-isolated by default
        status="success",
        msg_type="json",
        event=type,
        data={"text": text},
        metadata=metadata,
        simulation_id=simulation_id,
    )


async def emit_inter_agent_pulse(
    session_id: str,
    from_agent: str,
    to_agent: str,
    message: str,
    direction: str = "request",
    simulation_id: Optional[str] = None,
):
    """Legacy wrapper for inter-agent communication visibility."""
    if direction == "request":
        text = f"📢 {from_agent} -> {to_agent}: {message}"
    else:
        text = f"📨 {from_agent} <- {to_agent}: {message}"

    await emit_narrative_pulse(
        session_id=session_id,
        text=text,
        type="inter-agent",
        author=from_agent,
        simulation_id=simulation_id,
    )


# [END emit_narrative_pulse]


async def emit_telemetry_pulse(
    session_id: str,
    payload: dict,
    type: str = "agent-telemetry",
    simulation_id: Optional[str] = None,
):
    """Legacy wrapper for raw telemetry events. Maps to emit_gateway_message."""
    agent_id = payload.get("agent", "system")
    event_type = payload.get("type", "telemetry")
    status = "error" if "error" in event_type else "info"

    await emit_gateway_message(
        origin={"type": "agent", "id": agent_id, "session_id": session_id},
        destination=[session_id],
        status=status,
        msg_type="telemetry",
        event=event_type,
        data=payload,
        metadata={"seq": payload.get("seq")},
        simulation_id=simulation_id,
    )
