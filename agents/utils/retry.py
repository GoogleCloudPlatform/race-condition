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

"""Centralized retry configuration for Gemini API calls.

All ADK agents and direct genai.Client calls should use these factories
to ensure 429 rate-limit errors (and other transient failures) are retried
with exponential backoff.

Usage in LlmAgent definitions::

    from agents.utils.retry import resilient_model

    agent = LlmAgent(
        model=resilient_model("gemini-3-flash-preview"),
        ...
    )

Usage for direct genai.Client calls::

    from agents.utils.retry import resilient_http_options

    client = genai.Client(
        http_options=resilient_http_options(api_version="v1beta1"),
    )

Environment variables (all optional):
    GEMINI_RETRY_ATTEMPTS      Total attempts including initial call (default: 5)
    GEMINI_RETRY_INITIAL_DELAY Seconds before first retry (default: 1.0)
    GEMINI_RETRY_MAX_DELAY     Maximum delay between retries (default: 60.0)
"""

import os

from google.genai import types

from agents.utils.global_gemini import GlobalGemini


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Read an integer from an environment variable with validation."""
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid integer") from None
    if value < minimum:
        raise ValueError(f"{name}={value} must be >= {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    """Read a float from an environment variable with validation."""
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid number") from None
    if value < minimum:
        raise ValueError(f"{name}={value} must be >= {minimum}")
    return value


def default_retry_options() -> types.HttpRetryOptions:
    """Build HttpRetryOptions from environment variables with sensible defaults.

    Returns retry config that handles 408, 429, 500, 502, 503, 504 errors
    with exponential backoff and jitter.

    Raises:
        ValueError: If env vars contain invalid values.
    """
    return types.HttpRetryOptions(
        attempts=_env_int("GEMINI_RETRY_ATTEMPTS", 5),
        initial_delay=_env_float("GEMINI_RETRY_INITIAL_DELAY", 1.0),
        max_delay=_env_float("GEMINI_RETRY_MAX_DELAY", 60.0),
        exp_base=2.0,
        jitter=1.0,
    )


def resilient_model(
    model_name: str,
    *,
    retry_options: types.HttpRetryOptions | None = None,
    location: str = "global",
) -> GlobalGemini:
    """Create a GlobalGemini instance with retry protection.

    Args:
        model_name: Gemini model identifier (e.g. "gemini-3-flash-preview").
        retry_options: Override retry config. Defaults to default_retry_options().
        location: Vertex AI API location. Defaults to "global" (required for
            Gemini 3 preview models). Set to a region like "us-central1" for
            GA models that should use a regional endpoint.
    """
    return GlobalGemini(
        model=model_name,
        retry_options=retry_options or default_retry_options(),
        location=location,
    )


def resilient_http_options(
    *,
    retry_options: types.HttpRetryOptions | None = None,
    **kwargs,
) -> types.HttpOptions:
    """Build HttpOptions with retry protection for direct genai.Client calls.

    Args:
        retry_options: Override retry config. Defaults to default_retry_options().
        **kwargs: Additional HttpOptions fields (api_version, headers, etc.).
    """
    return types.HttpOptions(
        retry_options=retry_options or default_retry_options(),
        **kwargs,
    )
