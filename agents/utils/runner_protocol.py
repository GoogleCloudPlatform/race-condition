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

"""Structured message protocol for runner agents.

Defines the contract between the simulator and runner agents. Both the
LLM-powered runner and the deterministic runner_autopilot consume these
messages. The simulator constructs them via serialize_runner_event().
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RunnerEventType(str, Enum):
    """Event types the simulator sends to runner agents."""

    START_GUN = "start_gun"
    CROWD_BOOST = "crowd_boost"
    DISTANCE_UPDATE = "distance_update"
    HYDRATION_STATION = "hydration_station"
    TICK = "tick"
    UNKNOWN = "unknown"


@dataclass
class RunnerEvent:
    """A parsed runner event with typed event and payload data."""

    event: RunnerEventType
    data: dict = field(default_factory=dict)


def parse_runner_event(text: str) -> RunnerEvent:
    """Parse a JSON message string into a RunnerEvent.

    Returns RunnerEvent with UNKNOWN type for malformed or unrecognized input.
    """
    if not text or not text.strip():
        return RunnerEvent(event=RunnerEventType.UNKNOWN)

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return RunnerEvent(event=RunnerEventType.UNKNOWN, data={"raw": text})

    if not isinstance(obj, dict) or "event" not in obj:
        return RunnerEvent(event=RunnerEventType.UNKNOWN, data=obj if isinstance(obj, dict) else {"raw": text})

    event_str = obj.get("event")
    data = {k: v for k, v in obj.items() if k != "event"}
    try:
        event_type = RunnerEventType(event_str)
    except ValueError:
        return RunnerEvent(event=RunnerEventType.UNKNOWN, data=data)

    return RunnerEvent(event=event_type, data=data)


def build_tick_event(
    tick: int,
    max_ticks: int,
    total_race_hours: float,
    race_distance_mi: float = 26.2188,
    collector_buffer_key: str = "",
    runner_count: int | None = None,
) -> RunnerEvent:
    """Build a TICK RunnerEvent with computed race timing data.

    Tick 0 is the initialization tick: ``minutes_per_tick=0`` so runners
    report their initial velocity at distance=0 without advancing.
    Movement ticks (1+) each cover ``minutes_per_tick`` of simulated time.

    Args:
        collector_buffer_key: Redis key for direct-write collection. When set,
            runners RPUSH their process_tick results directly to this key,
            enabling direct-write aggregation for faster tick processing.
    """
    minutes_per_tick = (total_race_hours * 60) / max_ticks if max_ticks > 0 else 0
    # Tick 0 is the initialization tick: no simulated time passes.
    tick_minutes = 0.0 if tick == 0 else minutes_per_tick
    data: dict = {
        "tick": tick,
        "max_ticks": max_ticks,
        "minutes_per_tick": tick_minutes,
        "elapsed_minutes": tick * minutes_per_tick,
        "race_distance_mi": race_distance_mi,
    }
    if collector_buffer_key:
        data["collector_buffer_key"] = collector_buffer_key
    if runner_count is not None:
        data["runner_count"] = runner_count
    return RunnerEvent(event=RunnerEventType.TICK, data=data)


def serialize_runner_event(event: RunnerEvent) -> str:
    """Serialize a RunnerEvent to a JSON string for transmission."""
    obj = {"event": event.event.value, **event.data}
    return json.dumps(obj)
