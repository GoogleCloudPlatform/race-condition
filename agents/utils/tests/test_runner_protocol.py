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

from agents.utils.runner_protocol import (
    RunnerEventType,
    RunnerEvent,
    build_tick_event,
    parse_runner_event,
    serialize_runner_event,
)


class TestRunnerEventType:
    def test_enum_values(self):
        assert RunnerEventType.START_GUN == "start_gun"
        assert RunnerEventType.CROWD_BOOST == "crowd_boost"
        assert RunnerEventType.DISTANCE_UPDATE == "distance_update"
        assert RunnerEventType.HYDRATION_STATION == "hydration_station"
        assert RunnerEventType.TICK == "tick"

    def test_unknown_value(self):
        assert RunnerEventType.UNKNOWN == "unknown"


class TestParseRunnerEvent:
    def test_start_gun(self):
        event = parse_runner_event('{"event": "start_gun"}')
        assert event.event == RunnerEventType.START_GUN
        assert event.data == {}

    def test_crowd_boost(self):
        event = parse_runner_event('{"event": "crowd_boost", "intensity": 0.8}')
        assert event.event == RunnerEventType.CROWD_BOOST
        assert event.data == {"intensity": 0.8}

    def test_distance_update(self):
        event = parse_runner_event('{"event": "distance_update", "mi_delta": 1.0}')
        assert event.event == RunnerEventType.DISTANCE_UPDATE
        assert event.data == {"mi_delta": 1.0}

    def test_hydration_station(self):
        event = parse_runner_event('{"event": "hydration_station"}')
        assert event.event == RunnerEventType.HYDRATION_STATION

    def test_tick(self):
        event = parse_runner_event('{"event": "tick", "tick": 5, "max_ticks": 24}')
        assert event.event == RunnerEventType.TICK
        assert event.data == {"tick": 5, "max_ticks": 24}

    def test_unknown_event_type(self):
        event = parse_runner_event('{"event": "solar_flare"}')
        assert event.event == RunnerEventType.UNKNOWN

    def test_malformed_json(self):
        event = parse_runner_event("not json at all")
        assert event.event == RunnerEventType.UNKNOWN

    def test_missing_event_field(self):
        event = parse_runner_event('{"foo": "bar"}')
        assert event.event == RunnerEventType.UNKNOWN

    def test_empty_string(self):
        event = parse_runner_event("")
        assert event.event == RunnerEventType.UNKNOWN


class TestBuildTickEvent:
    def test_tick_zero_is_init_tick(self):
        """Tick 0 is the init tick: minutes_per_tick=0, elapsed_minutes=0."""
        event = build_tick_event(tick=0, max_ticks=12, total_race_hours=6.0)
        assert event.event == RunnerEventType.TICK
        assert event.data["tick"] == 0
        assert event.data["max_ticks"] == 12
        assert event.data["minutes_per_tick"] == 0.0
        assert event.data["elapsed_minutes"] == 0.0
        assert event.data["race_distance_mi"] == 26.2188

    def test_mid_race_tick(self):
        """Tick 5 of 24, 6h race = 15 min/tick, elapsed = 5*15 = 75 min."""
        event = build_tick_event(tick=5, max_ticks=24, total_race_hours=6.0)
        assert event.data["minutes_per_tick"] == 15.0
        assert event.data["elapsed_minutes"] == 75.0  # 5*15

    def test_custom_race_distance(self):
        event = build_tick_event(tick=0, max_ticks=10, total_race_hours=2.0, race_distance_mi=13.1094)
        assert event.data["race_distance_mi"] == 13.1094

    def test_zero_max_ticks_returns_zero_timing(self):
        """Edge case: max_ticks=0 should not divide by zero."""
        event = build_tick_event(tick=0, max_ticks=0, total_race_hours=6.0)
        assert event.data["minutes_per_tick"] == 0
        assert event.data["elapsed_minutes"] == 0

    def test_last_tick(self):
        """Last tick (tick=24 of 24) should have elapsed = 24 * 15 = 360 min."""
        event = build_tick_event(tick=24, max_ticks=24, total_race_hours=6.0)
        assert event.data["elapsed_minutes"] == 360.0  # 24*15

    def test_first_movement_tick(self):
        """Tick 1 (first movement tick) should advance minutes_per_tick of time."""
        event = build_tick_event(tick=1, max_ticks=6, total_race_hours=6.0)
        assert event.data["minutes_per_tick"] == 60.0
        assert event.data["elapsed_minutes"] == 60.0  # 1*60

    def test_build_tick_event_includes_runner_count(self):
        event = build_tick_event(tick=1, max_ticks=12, total_race_hours=6.0, runner_count=100)
        assert event.data["runner_count"] == 100

    def test_build_tick_event_runner_count_defaults_absent(self):
        event = build_tick_event(tick=1, max_ticks=12, total_race_hours=6.0)
        assert "runner_count" not in event.data


class TestSerializeRunnerEvent:
    def test_round_trip_start_gun(self):
        original = RunnerEvent(event=RunnerEventType.START_GUN, data={})
        text = serialize_runner_event(original)
        parsed = parse_runner_event(text)
        assert parsed.event == original.event

    def test_round_trip_crowd_boost(self):
        original = RunnerEvent(
            event=RunnerEventType.CROWD_BOOST,
            data={"intensity": 0.8},
        )
        text = serialize_runner_event(original)
        parsed = parse_runner_event(text)
        assert parsed.event == original.event
        assert parsed.data["intensity"] == 0.8

    def test_serialized_format(self):
        event = RunnerEvent(event=RunnerEventType.START_GUN, data={})
        text = serialize_runner_event(event)
        obj = json.loads(text)
        assert obj["event"] == "start_gun"
