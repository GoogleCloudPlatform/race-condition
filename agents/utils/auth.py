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

"""Shared OIDC helper for AE / Cloud Run service-to-service calls.

Two auth modes:
  - IAP (dev/prod): audience = IAP_CLIENT_ID.
  - Cloud Run IAM (OSS): audience = target service's .run.app URL.

Python mirror of internal/auth/idtoken.go.
"""

from __future__ import annotations

import os
from functools import lru_cache

import google.auth.transport.requests
from google.oauth2 import id_token


@lru_cache(maxsize=1)
def _request() -> google.auth.transport.requests.Request:
    """Lazy-build the urllib3-backed transport (cached). Lazy so importing
    this module has no side effects -- helps tests that don't want a
    connection pool spinning up at collection time.
    """
    return google.auth.transport.requests.Request()


def resolve_audience(fallback_url: str) -> str:
    """OIDC audience for a downstream service: IAP_CLIENT_ID if set, else fallback_url.

    Empty return means "do not attach a token" (matches get_id_token's contract).
    """
    return os.environ.get("IAP_CLIENT_ID") or fallback_url


def get_id_token(audience: str) -> str | None:
    """Mint a Google-signed OIDC ID token for ``audience``.

    Returns None if the audience is empty or the underlying library raises
    (no ADC, network error, etc.). Callers treat None as "skip the
    Authorization header".
    """
    if not audience:
        return None
    try:
        return id_token.fetch_id_token(_request(), audience)
    except Exception:  # noqa: BLE001 -- any failure -> no token, caller decides
        return None
