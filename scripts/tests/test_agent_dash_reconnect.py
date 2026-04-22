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

"""Tests for agent_dash PubSub subscriber reconnect with backoff."""

import threading
from unittest.mock import MagicMock, patch


def _get_module():
    """Import agent_dash module, avoiding module-level side effects."""
    import importlib

    return importlib.import_module("scripts.core.agent_dash")


class TestPubSubReconnectBackoff:
    """Tests for exponential backoff in start_subscriber reconnect."""

    def _failing_subscribe(self, *args, **kwargs):
        """Create a mock future that raises on .result()."""
        future = MagicMock()
        future.result.side_effect = Exception("Connection lost")
        future.cancel = MagicMock()
        return future

    def _patch_pubsub(self, mod, stop_event, sleep_values, max_sleeps):
        """Return a context manager that patches PubSub clients and time.sleep."""

        def capture_sleep(seconds):
            sleep_values.append(seconds)
            if len(sleep_values) >= max_sleeps:
                stop_event.set()

        mock_sub = MagicMock()
        mock_sub.__enter__ = MagicMock(return_value=mock_sub)
        mock_sub.__exit__ = MagicMock(return_value=False)
        mock_sub.subscribe.side_effect = self._failing_subscribe
        mock_sub.topic_path.return_value = "projects/test/topics/t"
        mock_sub.subscription_path.return_value = "projects/test/subscriptions/s"

        mock_pub = MagicMock()

        return (
            patch.object(mod.pubsub_v1, "SubscriberClient", return_value=mock_sub),
            patch.object(mod.pubsub_v1, "PublisherClient", return_value=mock_pub),
            patch("time.sleep", side_effect=capture_sleep),
            patch("random.uniform", return_value=0),
        )

    def test_reconnect_uses_exponential_backoff(self):
        """Reconnect delay should increase exponentially after failures."""
        mod = _get_module()
        sleep_values: list[float] = []
        stop_event = threading.Event()

        patches = self._patch_pubsub(mod, stop_event, sleep_values, 4)
        with patches[0], patches[1], patches[2], patches[3]:
            mod.start_subscriber(stop_event=stop_event)

        assert len(sleep_values) >= 4
        assert sleep_values[0] == 5.0
        assert sleep_values[1] == 10.0
        assert sleep_values[2] == 20.0
        assert sleep_values[3] == 40.0

    def test_backoff_caps_at_60_seconds(self):
        """Backoff should never exceed 60 seconds (+ jitter)."""
        mod = _get_module()
        sleep_values: list[float] = []
        stop_event = threading.Event()

        patches = self._patch_pubsub(mod, stop_event, sleep_values, 6)
        with patches[0], patches[1], patches[2], patches[3]:
            mod.start_subscriber(stop_event=stop_event)

        for val in sleep_values:
            assert val <= 75.0, f"Sleep value {val} exceeds cap"

    def test_backoff_resets_on_successful_connection(self):
        """After a successful pull cycle, backoff should reset to 5s."""
        mod = _get_module()
        sleep_values: list[float] = []
        stop_event = threading.Event()
        call_count = 0

        def capture_sleep(seconds):
            sleep_values.append(seconds)
            if len(sleep_values) >= 3:
                stop_event.set()

        def flaky_subscribe(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            future = MagicMock()
            if call_count == 2:
                # Second attempt succeeds (result() returns normally)
                future.result.return_value = None
            else:
                future.result.side_effect = Exception("Connection lost")
            future.cancel = MagicMock()
            return future

        mock_sub = MagicMock()
        mock_sub.__enter__ = MagicMock(return_value=mock_sub)
        mock_sub.__exit__ = MagicMock(return_value=False)
        mock_sub.subscribe.side_effect = flaky_subscribe
        mock_sub.topic_path.return_value = "projects/test/topics/t"
        mock_sub.subscription_path.return_value = "projects/test/subscriptions/s"

        mock_pub = MagicMock()

        with (
            patch.object(mod.pubsub_v1, "SubscriberClient", return_value=mock_sub),
            patch.object(mod.pubsub_v1, "PublisherClient", return_value=mock_pub),
            patch("time.sleep", side_effect=capture_sleep),
            patch("random.uniform", return_value=0),
        ):
            mod.start_subscriber(stop_event=stop_event)

        # First failure: backoff 5s
        assert sleep_values[0] == 5.0
        # Second attempt succeeds, backoff resets
        # Third failure: should be back to 5s (not 10s)
        assert sleep_values[1] == 5.0

    def test_stop_event_terminates_loop(self):
        """Setting stop_event should cause start_subscriber to exit."""
        mod = _get_module()
        stop_event = threading.Event()
        stop_event.set()  # Pre-set so loop exits immediately

        with (
            patch.object(mod.pubsub_v1, "SubscriberClient", return_value=MagicMock()),
            patch.object(mod.pubsub_v1, "PublisherClient", return_value=MagicMock()),
        ):
            # Should return immediately without blocking
            mod.start_subscriber(stop_event=stop_event)
