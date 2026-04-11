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

Race Condition runs in two auth modes:

  - IAP mode (dev/prod): the gateway sits behind Identity-Aware Proxy
    and per-user OIDC tokens are minted with audience=IAP_CLIENT_ID.
  - Cloud Run IAM mode (OSS): no IAP brand exists; service-to-service
    calls authenticate against Cloud Run's roles/run.invoker check
    using OIDC tokens whose audience is the target service's URL.

This is the Python mirror of internal/auth/idtoken.go (Go).
"""

from __future__ import annotations

import os
from functools import lru_cache

import google.auth.transport.requests
from google.oauth2 import id_token


def resolve_audience(fallback_url: str) -> str:
    """Return the OIDC audience for invoking a downstream service.

    IAP_CLIENT_ID wins when set (dev/prod IAP-fronted gateway).
    Otherwise ``fallback_url`` is used (OSS Cloud Run IAM mode where
    the audience must equal the target service's .run.app URL).

    An empty return value means "do not attach a token" -- callers
    treat this as a no-op (matches ``get_id_token``'s contract).
    """
    iap = os.environ.get("IAP_CLIENT_ID")
    if iap:
        return iap
    return fallback_url


@lru_cache(maxsize=1)
def _request() -> google.auth.transport.requests.Request:
    """Process-wide google.auth Request object, reused across token fetches."""
    return google.auth.transport.requests.Request()


def get_id_token(audience: str) -> str | None:
    """Mint a Google-signed OIDC ID token for ``audience``.

    Returns ``None`` if the audience is empty or if the underlying
    library raises (no ADC, network error, etc.). Callers are expected
    to treat ``None`` as "skip the Authorization header" -- this matches
    the no-op contract of an empty audience.
    """
    if not audience:
        return None
    try:
        return id_token.fetch_id_token(_request(), audience)
    except Exception:  # noqa: BLE001 -- any failure -> no token, caller decides
        return None
