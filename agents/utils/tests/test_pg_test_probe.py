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

"""Tests for the auth-aware Postgres test-availability probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncpg


def test_probe_returns_false_on_invalid_password():
    """When dev postgres squats the port, asyncpg raises InvalidPasswordError."""
    from agents.utils.tests.test_db_session_integration import _test_pg_available

    async def _raise(*args, **kwargs):
        raise asyncpg.exceptions.InvalidPasswordError("nope")

    with patch("asyncpg.connect", new=AsyncMock(side_effect=_raise)):
        assert _test_pg_available() is False


def test_probe_returns_false_on_connection_refused():
    """When nothing is listening on 8104, the probe should skip cleanly."""
    from agents.utils.tests.test_db_session_integration import _test_pg_available

    async def _raise(*args, **kwargs):
        raise OSError("Connection refused")

    with patch("asyncpg.connect", new=AsyncMock(side_effect=_raise)):
        assert _test_pg_available() is False


def test_probe_returns_true_on_successful_connect():
    """When hermetic test postgres is reachable, the probe should return True."""
    from agents.utils.tests.test_db_session_integration import _test_pg_available

    fake_conn = AsyncMock()
    fake_conn.close = AsyncMock(return_value=None)

    async def _ok(*args, **kwargs):
        return fake_conn

    with patch("asyncpg.connect", new=AsyncMock(side_effect=_ok)):
        assert _test_pg_available() is True
