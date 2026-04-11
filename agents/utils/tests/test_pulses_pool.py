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

"""Tests for pulses.py Redis connection pool integration."""

from unittest.mock import patch, MagicMock

import agents.utils.pulses as pulses_mod


class TestPulsesPool:
    def test_uses_shared_redis_client(self):
        """pulses should delegate to the shared redis pool."""
        mock_client = MagicMock()
        with patch(
            "agents.utils.redis_pool.get_shared_redis_client",
            return_value=mock_client,
        ):
            client = pulses_mod._get_redis_client()
            assert client is mock_client
