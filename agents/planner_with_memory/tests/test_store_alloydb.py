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

"""Tests for AlloyDB store password resolution and DSN construction."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

import agents.planner_with_memory.memory.store_alloydb as mod


def _make_sm_response(payload: bytes) -> MagicMock:
    mock_payload = MagicMock()
    mock_payload.data = payload
    mock_response = MagicMock()
    mock_response.payload = mock_payload
    return mock_response


def _make_sm_client(response: MagicMock | None = None, side_effect: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if side_effect:
        client.access_secret_version.side_effect = side_effect
    elif response:
        client.access_secret_version.return_value = response
    return client


def _patch_sm(client: MagicMock):
    return patch(
        "agents.planner_with_memory.memory.store_alloydb._get_sm_client",
        return_value=client,
    )


class TestResolvePassword:
    def setup_method(self) -> None:
        mod._cached = None
        mod._sm_client = None

    def test_returns_env_var_when_set(self) -> None:
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": "localdev"}):
            assert mod._resolve_password() == "localdev"

    def test_empty_env_var_triggers_sm_fetch(self) -> None:
        client = _make_sm_client(response=_make_sm_response(b"sm-password"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            assert mod._resolve_password() == "sm-password"
        client.access_secret_version.assert_called_once()

    def test_caches_across_calls(self) -> None:
        client = _make_sm_client(response=_make_sm_response(b"cached-pw"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            assert mod._resolve_password() == "cached-pw"
            assert mod._resolve_password() == "cached-pw"
        assert client.access_secret_version.call_count == 1

    def test_refetches_after_ttl_expires(self) -> None:
        client = _make_sm_client(response=_make_sm_response(b"fresh-pw"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            mod._resolve_password()
            # Expire the cache
            pw, _ = mod._cached  # type: ignore[misc]
            mod._cached = (pw, time.monotonic() - mod._SECRET_TTL_SECONDS - 1)
            mod._resolve_password()
        assert client.access_secret_version.call_count == 2

    def test_raises_when_fetch_fails_and_no_cache(self) -> None:
        client = _make_sm_client(side_effect=RuntimeError("SM down"))
        with (
            patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}),
            _patch_sm(client),
            pytest.raises(ValueError, match="fetch.*password"),
        ):
            mod._resolve_password()

    def test_returns_stale_cache_when_refresh_fails(self) -> None:
        mod._cached = ("stale-pw", time.monotonic() - mod._SECRET_TTL_SECONDS - 1)
        client = _make_sm_client(side_effect=RuntimeError("SM down"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            assert mod._resolve_password() == "stale-pw"

    def test_uses_correct_secret_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _SM_PROJECT is captured at import time; setenv would be too late.
        monkeypatch.setattr(mod, "_SM_PROJECT", "sentinel-project-xyz")
        client = _make_sm_client(response=_make_sm_response(b"pw"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            mod._resolve_password()
        name = client.access_secret_version.call_args.kwargs["name"]
        assert "sentinel-project-xyz" in name
        assert "am-db-password" in name

    def test_strips_whitespace_from_payload(self) -> None:
        client = _make_sm_client(response=_make_sm_response(b"  secret-pw\n"))
        with patch.dict("os.environ", {"ALLOYDB_PASSWORD": ""}), _patch_sm(client):
            assert mod._resolve_password() == "secret-pw"


class TestGetDsn:
    def setup_method(self) -> None:
        mod._cached = None
        mod._sm_client = None

    def test_uses_env_password_directly(self) -> None:
        env = {
            "ALLOYDB_HOST": "10.0.0.1",
            "ALLOYDB_PASSWORD": "mypass",
            "ALLOYDB_DATABASE": "testdb",
            "ALLOYDB_USER": "testuser",
            "ALLOYDB_PORT": "5432",
        }
        with patch.dict("os.environ", env, clear=False):
            dsn = mod._get_dsn()
        assert "mypass" in dsn
        assert "10.0.0.1" in dsn
        assert "testdb" in dsn
        assert "testuser" in dsn

    def test_raises_without_host(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="ALLOYDB_HOST"),
        ):
            mod._get_dsn()
