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

import asyncio
import json
import logging
import os
import random
import threading
import time
import uuid
import redis.asyncio as redis
from typing import Optional, Any
from opentelemetry import context as otel_context
from google.genai import types
import agents.utils.pulses as pulses_util
from agents.utils.redis_pool import get_shared_redis_client
from agents.utils import simulation_registry

logger = logging.getLogger(__name__)

NUM_SPAWN_SHARDS = 8


def spawn_queue_names(agent_type: str, num_shards: int = NUM_SPAWN_SHARDS) -> list[str]:
    """Return all shard queue names for an agent type."""
    return [f"simulation:spawns:{agent_type}:{i}" for i in range(num_shards)]


class RedisOrchestratorDispatcher:
    """Listens for orchestration events on Redis and dispatches them to the local runner.

    Runs in a background thread to ensure it's always listening regardless of the ADK lifecycle.
    """

    def __init__(
        self,
        runner: Any,
        redis_url: Optional[str] = None,
        dispatch_mode: str = "subscriber",
        suppress_gateway_emission: bool = False,
    ):
        self.runner = runner
        self.dispatch_mode = dispatch_mode
        self.suppress_gateway_emission = suppress_gateway_emission
        self.redis_url = redis_url or os.getenv("REDIS_ADDR", "")
        if not self.redis_url.startswith("redis://"):
            self.redis_url = f"redis://{self.redis_url}"

        # Try to discover agent and app names from runner
        self.agent_type = "unknown"
        self.allowed_authors = {"agent", "tool", "model"}
        if hasattr(runner, "app"):
            if hasattr(runner.app, "name"):
                self.agent_type = runner.app.name
                self.allowed_authors.add(runner.app.name)
            if hasattr(runner.app, "root_agent") and hasattr(runner.app.root_agent, "name"):
                self.allowed_authors.add(runner.app.root_agent.name)
        elif hasattr(runner, "app_name"):
            self.agent_type = runner.app_name
            self.allowed_authors.add(runner.app_name)

        logger.info(
            f"ORCHESTRATION_INIT: Dispatcher initialized for agent type: "
            f"{self.agent_type}, allowed: {self.allowed_authors}"
        )
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self.active_sessions = set()
        self._seen_events = set()
        self._background_tasks = set()  # Track to prevent GC issues
        self._session_locks: dict[str, asyncio.Lock] = {}
        self.session_simulation_map: dict[str, str] = {}
        self._simulation_subscriptions: set[str] = set()
        self._pubsub = None  # Active Redis pubsub instance for dynamic subscription

    def start(self):
        """Starts the background Redis listener in a dedicated thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        logger.info(f"ORCHESTRATION_LIFECYCLE: Thread started for {self.agent_type}")

    async def _cancel_all_tasks(self):
        """Internal helper to cancel all tasks in the current loop."""
        tasks = [t for t in asyncio.all_tasks(self._loop) if t is not asyncio.current_task()]
        if not tasks:
            return

        logger.debug(f"ORCHESTRATION_LIFECYCLE: Cancelling {len(tasks)} tasks...")
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        """Stops the background Redis listener."""
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            # Simply stop the loop; the thread will handle cleanup in finally block
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=5.0)
            self._thread = None
        logger.info(f"ORCHESTRATION_LIFECYCLE: Thread stopped for {self.agent_type}")

    async def _unsubscribe_scoped_channel(self, sim_id: str) -> None:
        """Unsubscribe from a simulation-scoped broadcast channel.

        Called internally when no sessions remain for a given simulation_id.
        """
        scoped_channel = f"simulation:{sim_id}:broadcast"
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(scoped_channel)
                logger.info(f"ORCHESTRATION_LIFECYCLE: Unsubscribed from {scoped_channel}")
            except Exception as e:
                logger.error(f"ORCHESTRATION_ERROR: Failed to unsubscribe from {scoped_channel}: {e}")

    def remove_session(self, session_id: str) -> None:
        """Remove a session and clean up simulation tracking state.

        Removes the session from active_sessions, session_simulation_map, and
        — if no other sessions remain for its simulation — from
        _simulation_subscriptions (with an async unsubscribe from the scoped
        Redis channel).

        This method is safe to call from any thread; the async unsubscribe is
        scheduled on the dispatcher's event loop if it's running.
        """
        self.active_sessions.discard(session_id)
        sim_id = self.session_simulation_map.pop(session_id, None)
        # Schedule async registry cleanup using the same pattern as
        # _unsubscribe_scoped_channel — keeps remove_session() sync.
        simulation_registry._local.pop(session_id, None)  # immediate L1 cleanup
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda sid=session_id: asyncio.ensure_future(simulation_registry.unregister(sid)),
            )

        if sim_id is not None:
            # Check if any other sessions still belong to this simulation
            remaining = any(s == sim_id for s in self.session_simulation_map.values())
            if not remaining and sim_id in self._simulation_subscriptions:
                self._simulation_subscriptions.discard(sim_id)
                # Schedule the unsubscribe on the dispatcher's event loop
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(
                        lambda sid=sim_id: asyncio.ensure_future(self._unsubscribe_scoped_channel(sid)),
                    )
                logger.info(f"ORCHESTRATION_LIFECYCLE: Cleaned up simulation {sim_id} (no remaining sessions)")

        logger.info(
            f"ORCHESTRATION_LIFECYCLE: Removed session {session_id} "
            f"(active={len(self.active_sessions)}, sims={len(self._simulation_subscriptions)})"
        )

    def _run_thread(self):
        """Thread entry point: creates a new event loop and runs the listener."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            # Run the main listener loop
            self._loop.run_until_complete(self._listen_loop())
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error(f"ORCHESTRATION_ERROR: Loop error: {e}")
        finally:
            # CLEANUP: Cancel all pending tasks before closing the loop
            try:
                self._loop.run_until_complete(self._cancel_all_tasks())
                # Process any pending callbacks (like cancellations finishing)
                self._loop.run_until_complete(asyncio.sleep(0.1))
            except Exception as e:
                logger.debug(f"ORCHESTRATION_LIFECYCLE: Cleanup error: {e}")

            self._loop.close()
            self._loop = None

    async def _listen_loop(self):
        """Main loop that runs both Pub/Sub and Queue listeners."""
        if self.dispatch_mode == "callable":
            logger.info(f"ORCHESTRATION_LIFECYCLE: Callable mode — HTTP only, no Redis listeners for {self.agent_type}")
            # Callable agents (Agent Engine) cannot connect to Redis.
            # They receive events solely via HTTP orchestration pushes.
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
            return

        backoff = 5  # Initial backoff seconds
        while not self._stop_event.is_set():
            try:
                r = get_shared_redis_client()
                if r is None:
                    logger.error("ORCHESTRATION_ERROR: No Redis client available (REDIS_ADDR not set?)")
                    await asyncio.sleep(backoff)
                    continue
                # Run both listeners concurrently.  If EITHER exits
                # (crash, disconnect, pool exhaustion), cancel the
                # survivor and restart both via the outer loop.
                # asyncio.gather waits for ALL tasks — a silently-
                # returning listener leaves gather blocking on the
                # surviving one, preventing reconnection forever.
                pubsub_task = asyncio.ensure_future(self._pubsub_listener(r))
                queue_task = asyncio.ensure_future(self._queue_listener(r))
                try:
                    done, pending = await asyncio.wait(
                        [pubsub_task, queue_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    # Cancel the surviving listener so both restart together
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                    # Re-raise if the completed task had an exception
                    for task in done:
                        exc = task.exception()
                        if exc is not None:
                            raise exc
                except (asyncio.CancelledError, GeneratorExit):
                    pubsub_task.cancel()
                    queue_task.cancel()
                    raise
                backoff = 5  # Reset on successful connection cycle
            except (asyncio.CancelledError, GeneratorExit):
                break
            except Exception as e:
                if not self._stop_event.is_set():
                    jitter = random.uniform(0, backoff * 0.25)
                    logger.error(
                        "ORCHESTRATION_ERROR: Listener loop crash, reconnecting in %.1fs: %s",
                        backoff + jitter,
                        e,
                    )
                    await asyncio.sleep(backoff + jitter)
                    backoff = min(backoff * 2, 60)  # Double, cap at 60s

    async def _pubsub_listener(self, r: redis.Redis):
        """Listens for global and simulation-scoped broadcast pulses via Pub/Sub."""
        channel_name = "simulation:broadcast"
        try:
            async with r.pubsub() as pubsub:
                self._pubsub = pubsub
                await pubsub.subscribe(channel_name)
                logger.info(f"ORCHESTRATION_PUB/SUB: Subscribed to {channel_name}")

                # Re-subscribe to any simulation channels from a prior connection cycle
                for sim_id in list(self._simulation_subscriptions):
                    scoped = f"simulation:{sim_id}:broadcast"
                    await pubsub.subscribe(scoped)
                    logger.info(f"ORCHESTRATION_PUB/SUB: Re-subscribed to {scoped}")

                while not self._stop_event.is_set():
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if message and message["type"] == "message":
                            await self._handle_message(r, message["data"])
                    except (GeneratorExit, asyncio.CancelledError):
                        return
                    except Exception as e:
                        if not self._stop_event.is_set():
                            logger.error(f"ORCHESTRATION_ERROR: PubSub read error: {e}")
                        break  # Reconnect
        except asyncio.CancelledError:
            return
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error(f"ORCHESTRATION_ERROR: PubSub connection error: {e}")
        finally:
            self._pubsub = None

    async def _queue_listener(self, r: redis.Redis):
        """Listens for targeted spawn events via Redis List (Queue)."""
        queues = spawn_queue_names(self.agent_type)
        logger.info(f"ORCHESTRATION_QUEUE: Listening on {len(queues)} shards: {queues}")

        while not self._stop_event.is_set():
            try:
                # BLPOP from all shards — Redis returns first available
                # Randomize order to avoid priority bias (BLPOP prioritizes first key)
                shuffled = list(queues)
                random.shuffle(shuffled)
                res = await r.blpop(shuffled, timeout=1)  # type: ignore[reportGeneralTypeIssues,misc]
                if res:
                    _, data = res
                    await self._handle_message(r, data)
            except (GeneratorExit, asyncio.CancelledError):
                return
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"ORCHESTRATION_ERROR: Queue read error: {e}")
                    await asyncio.sleep(1)
                break  # Reconnect

    async def handle_event(self, data: dict):
        """Processes an orchestration event pushed via HTTP."""
        return await self._process_event(data)

    async def _handle_message(self, r: redis.Redis, data_str: bytes):
        """Processes a message from Redis Pub/Sub or Queue."""
        try:
            data = json.loads(data_str)
            await self._process_event(data)
        except Exception as e:
            logger.error(f"ORCHESTRATION_ERROR: Failed to handle Redis message: {e}")

    async def _process_event(self, data: dict):
        """Core event processing logic shared by Push and Pull models."""
        try:
            msg_type = data.get("type")
            event_id = data.get("eventId")

            if event_id:
                if event_id in self._seen_events:
                    logger.debug(f"ORCHESTRATION_DEDUPE: Skipping duplicate event {event_id}")
                    return
                self._seen_events.add(event_id)
                # Keep cache small
                if len(self._seen_events) > 1000:
                    # Pop oldest items (approximate)
                    self._seen_events.remove(next(iter(self._seen_events)))

            # sessionId can be at top level or inside payload depending on source
            session_id = data.get("sessionId") or data.get("payload", {}).get("sessionId")

            logger.info(f"SIMULATION_EVENT: Incoming [{msg_type}] for {session_id}")

            if msg_type == "environment_reset":
                session_count = len(self.active_sessions)
                task_count = len(self._background_tasks)
                logger.info(
                    f"ORCHESTRATION_RESET: Environment reset received. "
                    f"Clearing {session_count} session(s) and cancelling {task_count} task(s)"
                )
                # Cancel all in-flight run_async tasks
                for future in list(self._background_tasks):
                    future.cancel()
                self._background_tasks.clear()
                # Clear session tracking
                self.active_sessions.clear()
                # Clear per-session locks
                self._session_locks.clear()
                # Clear dedup cache
                self._seen_events.clear()
                await simulation_registry.clear()
                return

            elif msg_type == "spawn_agent":
                payload = data.get("payload", {})
                target_agent_type = payload.get("agentType")

                if target_agent_type == self.agent_type:
                    logger.info(f"ORCHESTRATION_EVENT: Spawning session {session_id} (type: {target_agent_type})")
                    self.active_sessions.add(session_id)

                    # Track simulation_id for scoped broadcast subscription
                    sim_id = payload.get("simulation_id")
                    if sim_id:
                        self.session_simulation_map[session_id] = sim_id
                        await simulation_registry.register(session_id, sim_id)
                        if sim_id not in self._simulation_subscriptions:
                            self._simulation_subscriptions.add(sim_id)
                            scoped_channel = f"simulation:{sim_id}:broadcast"
                            # Dynamically subscribe to the scoped channel
                            if self._pubsub is not None:
                                try:
                                    await self._pubsub.subscribe(scoped_channel)
                                    logger.info(f"ORCHESTRATION_EVENT: Subscribed to {scoped_channel}")
                                except Exception as e:
                                    logger.error(f"ORCHESTRATION_ERROR: Failed to subscribe to {scoped_channel}: {e}")
                            else:
                                logger.info(
                                    f"ORCHESTRATION_EVENT: Will subscribe to {scoped_channel} on next pubsub connect"
                                )

                    # Session creation is deferred to the first run_async() call,
                    # which auto-creates via Runner(auto_create_session=True).
                    # No DB round-trip needed at spawn time.
                else:
                    logger.debug(f"ORCHESTRATION_EVENT: Ignored spawn for {target_agent_type}")

            elif msg_type == "broadcast":
                payload = data.get("payload", {})
                broadcast_data = payload.get("data", "PULSE")
                targets = payload.get("targets")  # Optional list of session IDs

                logger.info(
                    f"ORCHESTRATION_EVENT: Processing pulse: {broadcast_data} "
                    f"(Targets: {len(targets) if targets else 'all'}, "
                    f"active_sessions={len(self.active_sessions)})"
                )

                # Prepare content: if broadcast_data is JSON from UI, extract 'text'
                user_msg = broadcast_data
                try:
                    inner = json.loads(broadcast_data)
                    if isinstance(inner, dict) and "text" in inner:
                        user_msg = inner["text"]
                except Exception:
                    pass

                content = types.Content(role="user", parts=[types.Part(text=user_msg)])

                # Filter targets.  When the broadcast carries a
                # simulation_id, ONLY trigger sessions belonging to
                # that simulation — never cross-contaminate.
                broadcast_sim_id = data.get("simulation_id")
                to_trigger = []
                if broadcast_sim_id:
                    # Simulation-scoped: only runners for THIS simulation
                    to_trigger = [
                        sid for sid in self.active_sessions if self.session_simulation_map.get(sid) == broadcast_sim_id
                    ]
                elif targets:
                    if self.agent_type in targets:
                        to_trigger = list(self.active_sessions)
                    else:
                        to_trigger = [sid for sid in targets if sid in self.active_sessions]
                else:
                    to_trigger = list(self.active_sessions)

                # Exclude finished/collapsed runners from fan-out
                exclude_ids = payload.get("exclude_runner_ids")
                if exclude_ids:
                    exclude_set = set(exclude_ids)
                    to_trigger = [sid for sid in to_trigger if sid not in exclude_set]

                # The gateway's DispatchToAgent sends targeted broadcasts
                # via HTTP POST to ONE random Cloud Run instance.  With
                # min_instances=5, this instance likely owns only a subset
                # of the target sessions.  We must:
                #  1. Trigger sessions we own.
                #  2. Re-publish to Redis pub/sub so other instances
                #     can trigger their sessions.
                #
                # We generate an eventId for dedup (the gateway sends
                # empty eventId for targeted dispatches).
                unmatched = set(targets or []) - set(to_trigger) if targets else set()
                # Only relay from the initial HTTP delivery, never
                # re-relay a message that already came through pub/sub.
                already_relayed = data.get("_relayed", False)

                logger.info(
                    f"ORCHESTRATION_EVENT: Broadcast filter: "
                    f"matched={len(to_trigger)}, unmatched={len(unmatched)}, "
                    f"relayed={already_relayed}, "
                    f"active_sessions={len(self.active_sessions)}"
                )

                if unmatched and not already_relayed:
                    try:
                        redis_addr = os.environ.get("REDIS_ADDR", "")
                        if redis_addr:
                            url = redis_addr if redis_addr.startswith("redis://") else f"redis://{redis_addr}"
                            # Fresh connection avoids event-loop mismatch
                            # when HTTP handler (uvicorn) vs dispatcher thread.
                            relay_conn = redis.from_url(url)
                            try:
                                relay_id = f"relay-{uuid.uuid4().hex[:12]}"
                                self._seen_events.add(relay_id)
                                relay_data = dict(data)
                                relay_data["eventId"] = relay_id
                                relay_data["_relayed"] = True
                                relay_data.setdefault("payload", {})["targets"] = list(unmatched)
                                # Derive the relay channel from the broadcast's
                                # simulation_id.  If the original broadcast was
                                # scoped (simulation:{sim_id}:broadcast), we must
                                # relay to the same scoped channel — otherwise
                                # other dispatcher instances subscribed only to
                                # the scoped channel would never see it.
                                broadcast_sim_id = data.get("simulation_id") or data.get("payload", {}).get(
                                    "simulation_id"
                                )
                                if broadcast_sim_id:
                                    relay_channel = f"simulation:{broadcast_sim_id}:broadcast"
                                else:
                                    relay_channel = "simulation:broadcast"
                                await relay_conn.publish(relay_channel, json.dumps(relay_data))
                                logger.info(
                                    f"ORCHESTRATION_EVENT: Relayed broadcast for "
                                    f"{len(unmatched)} unmatched sessions "
                                    f"to {relay_channel} (relayId={relay_id})"
                                )
                            finally:
                                await relay_conn.aclose()
                    except Exception as e:
                        logger.error(f"ORCHESTRATION_ERROR: Failed to relay broadcast: {e}")

                if not to_trigger:
                    return

                logger.info(
                    "PERF_TRACE: broadcast_received sessions_to_trigger=%d active=%d t=%.6f",
                    len(to_trigger),
                    len(self.active_sessions),
                    time.perf_counter(),
                )

                t_trigger_start = time.perf_counter()
                for sid in to_trigger:
                    try:
                        self._trigger_agent_run(sid, content)
                    except Exception as e:
                        logger.error(f"ORCHESTRATION_ERROR: Failed to trigger pulse for {sid}: {e}")
                t_trigger_end = time.perf_counter()
                logger.info(
                    "PERF_TRACE: broadcast_triggered count=%d elapsed_ms=%.1f",
                    len(to_trigger),
                    (t_trigger_end - t_trigger_start) * 1000,
                )

            elif msg_type == "end_simulation":
                sim_id = data.get("simulation_id")
                if sim_id:
                    # Remove all sessions belonging to this simulation
                    sessions_to_remove = [
                        sid for sid, mapped_sim in list(self.session_simulation_map.items()) if mapped_sim == sim_id
                    ]
                    for sid in sessions_to_remove:
                        self.remove_session(sid)
                    logger.info(
                        f"ORCHESTRATION_LIFECYCLE: Simulation {sim_id} ended, "
                        f"removed {len(sessions_to_remove)} session(s)"
                    )
                else:
                    logger.warning("ORCHESTRATION_EVENT: end_simulation without simulation_id, ignoring")

            elif msg_type == "a2ui_action":
                payload = data.get("payload", {})
                action_name = payload.get("actionName", "unknown")
                target_sid = data.get("sessionId") or payload.get("sessionId")

                logger.info(f"ORCHESTRATION_EVENT: A2UI action '{action_name}' for session {target_sid}")

                if target_sid and target_sid in self.active_sessions:
                    action_text = json.dumps(
                        {
                            "a2ui_action": action_name,
                            "source": "a2ui_button",
                        }
                    )
                    content = types.Content(
                        role="user",
                        parts=[types.Part(text=action_text)],
                    )
                    try:
                        self._trigger_agent_run(target_sid, content)
                    except Exception as e:
                        logger.error(f"ORCHESTRATION_ERROR: Failed to trigger A2UI action for {target_sid}: {e}")
                else:
                    logger.warning(f"ORCHESTRATION_EVENT: Session {target_sid} not active, ignoring A2UI action")

        except Exception as e:
            logger.error(f"ORCHESTRATION_ERROR: Event processing failed: {e}")

    async def _locked_trigger(self, session_id: str, content: Any):
        """Acquire a per-session lock, then run the agent logic.

        Serializes concurrent events for the same session (e.g. START_GUN +
        TICK-0 race) while allowing different sessions to run concurrently.
        """
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        async with lock:
            await self._trigger_agent_run_logic(session_id, content)

    def _trigger_agent_run(self, session_id: str, content: Any):
        """Helper to run the agent in the background."""
        # Ensure we use the correct event loop (our own internal loop)
        if self._loop and self._loop.is_running():
            task = asyncio.run_coroutine_threadsafe(self._locked_trigger(session_id, content), self._loop)
            # Add to set to prevent GC, and clean up when done
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            logger.error(f"ORCHESTRATION_ERROR: Cannot trigger run for {session_id}, event loop is not running.")

    async def _trigger_agent_run_logic(self, session_id: str, content: Any, pulses_collector: Optional[list] = None):
        """Core logic for running the agent and relaying results."""
        # Ensure we have a clean OTEL context for this background execution
        token = otel_context.attach(otel_context.Context())
        broadcast_to_redis = pulses_collector is None
        try:
            # NOTE: Session existence is handled by runner.run_async() internally
            # via _get_or_create_session(). Calling get_session() here was a
            # duplicate that added ~4 unnecessary DB round-trips per invocation.

            logger.info(f"SIMULATION_EVENT: Triggering run_async for {session_id}")
            # 3. Iterate through generator to execute and relay results
            t_run_start = time.perf_counter()
            gen = self.runner.run_async(user_id="simulation", session_id=session_id, new_message=content)
            async for event in gen:
                logger.debug(f"ORCHESTRATION_EVENT: Received event from runner for {session_id}")
                # FIX: Instead of joining all parts in an event, we create a pulse for each
                # This prevents concatenated JSON strings that break parsing.
                pulses = self._prepare_pulses(session_id, event)
                for pulse_text in pulses:
                    if pulses_collector is not None:
                        logger.debug(f"ORCHESTRATION_DEBUG: Appending to collector for {session_id}")
                        pulses_collector.append(pulse_text)

                    if broadcast_to_redis and not self.suppress_gateway_emission:
                        # Passthrough: emit pulse as text or json.
                        # A2UI extraction is handled exclusively by the
                        # plugin's _emit_narrative (tool_end JSON path).
                        # Strip fenced ```a2ui``` blocks from text so raw
                        # A2UI markup doesn't leak to the frontend.
                        import re

                        cleaned = re.sub(r"```a2ui\n[\s\S]*?(?:\n```|$)", "", pulse_text).strip()
                        emit_text = cleaned if cleaned else pulse_text

                        msg_type = "text"
                        event_type = "text"
                        emit_data = {"text": emit_text}

                        try:
                            parsed = json.loads(emit_text)
                            if isinstance(parsed, (dict, list)):
                                # Skip A2UI tool results — the plugin's
                                # _emit_narrative handles these with the
                                # correct msg_type="a2ui" wrapper.
                                if isinstance(parsed, dict) and "a2ui" in parsed:
                                    continue
                                emit_data = parsed
                                msg_type = "json"
                                event_type = "json"
                        except Exception:
                            pass  # Keep as text

                        sim_id = self.session_simulation_map.get(session_id)
                        await pulses_util.emit_gateway_message(
                            origin={
                                "type": "agent",
                                "id": self.agent_type,
                                "session_id": session_id,
                            },
                            destination=[session_id],
                            status="success",
                            msg_type=msg_type,
                            event=event_type,
                            data=emit_data,
                            simulation_id=sim_id,
                        )

            t_run_end = time.perf_counter()
            logger.info(
                "PERF_TRACE: run_async_complete session=%s elapsed_ms=%.1f",
                session_id,
                (t_run_end - t_run_start) * 1000,
            )
            logger.info(f"ORCHESTRATION_EVENT: Completed run_async for {session_id}")
        except Exception as run_err:
            import traceback

            logger.error(
                f"ORCHESTRATION_ERROR: Failed to trigger run for {session_id}: {run_err}\n{traceback.format_exc()}"
            )
        finally:
            try:
                otel_context.detach(token)
            except Exception as e:
                # This can happen during task cancellation or system shutdown
                logger.debug(f"ORCHESTRATION_DEBUG: OTEL context detach failed (likely noise): {e}")

    def _prepare_pulses(self, session_id: str, event: Any) -> list[Any]:
        """Converts an agent event into a list of payloads (strings).

        Mixed-content turns (text + function_call in the same Content)
        suppress the text Part: it is mid-turn planning narration ("I'll
        now call X"), not user-facing chat. Emitting it would defeat the
        FE's `previousMessageIsA2ui` suppression invariant because text
        reaches the wire before the function_call's tool result and the
        resulting a2ui event. Terminal turns (text-only, no
        function_calls) still emit cleanly.

        See docs/plans/2026-04-18-dispatcher-text-suppression-design.md.
        """
        if event.author not in self.allowed_authors:
            logger.debug(
                f"ORCHESTRATION_FILTER: Ignoring event from author '{event.author}' (Allowed: {self.allowed_authors})"
            )
            return []

        has_function_call = (
            any(getattr(p, "function_call", None) for p in event.content.parts)
            if event.content and event.content.parts
            else False
        )

        payloads = []
        if event.content and event.content.parts:
            for p in event.content.parts:
                text = ""
                if p.text:
                    if has_function_call:
                        continue
                    text = p.text
                elif getattr(p, "function_response", None) and getattr(p.function_response, "response", None):
                    resp = p.function_response.response
                    try:
                        if isinstance(resp, (dict, list)):
                            text = json.dumps(resp)
                        else:
                            text = str(resp)
                    except Exception:
                        text = str(resp)

                if text:
                    logger.debug(f"ORCHESTRATION_EVENT: Relaying part from {event.author} for {session_id}")
                    payloads.append(text)

        return payloads
