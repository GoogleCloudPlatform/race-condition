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

"""Tests for PrunedRedisSessionService event pruning."""

from unittest.mock import MagicMock, patch

import pytest

from agents.utils.pruned_session_service import PrunedRedisSessionService


def _make_event(text: str = "hello") -> MagicMock:
    """Create a minimal mock Event."""
    event = MagicMock()
    event.timestamp = 1234567890.0
    event.actions = None
    return event


def _make_session(num_events: int = 0) -> MagicMock:
    """Create a minimal mock Session with N events."""
    session = MagicMock()
    session.id = "test-session"
    session.app_name = "test-app"
    session.user_id = "test-user"
    session.events = [_make_event(f"event-{i}") for i in range(num_events)]
    return session


@pytest.mark.asyncio
async def test_prune_before_parent_write():
    """Events must be pruned BEFORE super().append_event serializes the blob."""
    events_at_write_time = []

    # Patch RedisSessionService.append_event to capture session.events length at write time
    async def mock_parent_append(self, session, event):
        # Record how many events exist when parent would serialize
        events_at_write_time.append(len(session.events))
        # Simulate what parent does: add event to list
        session.events.append(event)
        return event

    with patch(
        "agents.utils.pruned_session_service.RedisSessionService.append_event",
        mock_parent_append,
    ):
        svc = PrunedRedisSessionService.__new__(PrunedRedisSessionService)
        svc.max_events = 2

        session = _make_session(num_events=10)
        event = _make_event("new")

        await svc.append_event(session, event)

        # Parent should have seen at most max_events events when it wrote
        assert events_at_write_time[0] <= 2


@pytest.mark.asyncio
async def test_events_bounded_after_multiple_appends():
    """After many appends, session.events stays bounded."""

    async def mock_parent_append(self, session, event):
        session.events.append(event)
        return event

    with patch(
        "agents.utils.pruned_session_service.RedisSessionService.append_event",
        mock_parent_append,
    ):
        svc = PrunedRedisSessionService.__new__(PrunedRedisSessionService)
        svc.max_events = 2

        session = _make_session(num_events=0)

        # Simulate 20 ticks worth of events (4 per tick)
        for i in range(80):
            await svc.append_event(session, _make_event(f"event-{i}"))

        # Events should be bounded: max_events + 1 (the just-appended one)
        assert len(session.events) <= 3


@pytest.mark.asyncio
async def test_no_prune_when_under_limit():
    """When events < max_events, no pruning occurs."""
    original_events: list[MagicMock] | None = None

    async def mock_parent_append(self, session, event):
        nonlocal original_events
        original_events = list(session.events)  # snapshot before parent adds
        session.events.append(event)
        return event

    with patch(
        "agents.utils.pruned_session_service.RedisSessionService.append_event",
        mock_parent_append,
    ):
        svc = PrunedRedisSessionService.__new__(PrunedRedisSessionService)
        svc.max_events = 10

        session = _make_session(num_events=3)
        await svc.append_event(session, _make_event("new"))

        # All 3 original events should still be present (no pruning)
        assert original_events is not None
        assert len(original_events) == 3


@pytest.mark.asyncio
async def test_default_max_events():
    """Default max_events should be 2."""
    with patch(
        "agents.utils.pruned_session_service.RedisSessionService.__init__",
        return_value=None,
    ):
        svc = PrunedRedisSessionService(host="localhost", port=6379)
        assert svc.max_events == 2
