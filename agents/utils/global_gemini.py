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

"""Gemini model subclass that routes to the global endpoint.

Agent Engine auto-configures vertexai with location='us-central1', which
prevents access to Gemini 3 preview models that require the global endpoint.

This module provides GlobalGemini — a drop-in replacement for Gemini that
explicitly creates a genai Client with location='global', bypassing AE's
platform-level vertexai.init() override.

Usage in LlmAgent definitions:
    from agents.utils.global_gemini import GlobalGemini

    agent = LlmAgent(
        model=GlobalGemini(model="gemini-3.5-flash"),
        ...
    )

Ref: https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/overview
"""

import asyncio
import logging
import os
from functools import cached_property
from typing import TYPE_CHECKING, AsyncGenerator

from google.adk.models.google_llm import Gemini
from google.genai import types
from pydantic import Field

if TYPE_CHECKING:
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.genai import Client

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class GlobalGemini(Gemini):
    """Gemini model with explicit location control for Vertex AI.

    On Agent Engine, vertexai is auto-initialized with the AE region
    (us-central1). The standard Gemini class creates Client() which
    inherits this location. GlobalGemini overrides api_client to create
    a Client with an explicit location, defaulting to 'global' for
    Gemini 3 preview models.

    For per-agent location control::

        # Global endpoint (the default; current Gemini 3.x models use it)
        model = GlobalGemini(model="gemini-3.5-flash")

        # Regional endpoint
        model = GlobalGemini(model="gemini-2.0-flash", location="us-central1")
    """

    location: str = "global"
    """Vertex AI API location. Defaults to 'global' for Gemini 3 preview models.
    Set to a region (e.g. 'us-central1') for GA models."""

    first_token_timeout_s: float = Field(
        default_factory=lambda: _env_float("GEMINI_MODEL_FIRST_TOKEN_TIMEOUT_S", 180.0)
    )
    """Seconds to wait for the first response chunk before treating the turn as
    stalled. A stall here is safe to restart (no output emitted yet)."""

    stream_timeout_s: float = Field(
        default_factory=lambda: _env_float("GEMINI_MODEL_STREAM_TIMEOUT_S", 120.0)
    )
    """Seconds to wait between subsequent chunks. A stall here is mid-stream and
    cannot be restarted, so it surfaces as an error."""

    stall_retries: int = Field(
        default_factory=lambda: _env_int("GEMINI_MODEL_STALL_RETRIES", 2)
    )
    """Number of from-scratch retries for a first-token stall (in addition to
    the initial attempt)."""

    async def generate_content_async(
        self, llm_request: "LlmRequest", stream: bool = False
    ) -> "AsyncGenerator[LlmResponse, None]":
        """Run the model with stall detection and bounded first-token recovery.

        The genai SDK retries only ``APIError`` responses, not client-side
        stalls. Production turns intermittently hang after ``model_start`` with
        the generation request wedged in-flight. We bound each chunk with
        ``asyncio.wait_for``: a stall before the first token is restarted from
        scratch (safe -- nothing emitted), a stall mid-stream is re-raised
        (restarting would duplicate output).
        """
        attempts = max(0, self.stall_retries) + 1
        for attempt in range(attempts):
            parent = super().generate_content_async(llm_request, stream=stream)
            yielded = False
            try:
                while True:
                    timeout = self.stream_timeout_s if yielded else self.first_token_timeout_s
                    try:
                        response = await asyncio.wait_for(parent.__anext__(), timeout)
                    except StopAsyncIteration:
                        return
                    yielded = True
                    yield response
            except (asyncio.TimeoutError, TimeoutError) as exc:
                await parent.aclose()
                if yielded or attempt == attempts - 1:
                    raise TimeoutError(
                        f"Gemini model turn stalled (model={self.model}, "
                        f"attempt {attempt + 1}/{attempts}, mid_stream={yielded})."
                    ) from exc
                logger.warning(
                    "Gemini model turn stalled before first token "
                    "(model=%s, attempt %d/%d); restarting.",
                    self.model,
                    attempt + 1,
                    attempts,
                )

    @cached_property
    def api_client(self) -> "Client":
        """Create a genai Client with the configured location."""
        from google.genai import Client

        api_key = os.environ.get("GEMINI_API_KEY")
        use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")

        if api_key and (not use_vertex or not project):
            return Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    headers=self._tracking_headers(),
                    retry_options=self.retry_options,
                    base_url=self.base_url,
                ),
            )

        return Client(
            vertexai=True,
            project=project or "",
            location=self.location,
            http_options=types.HttpOptions(
                headers=self._tracking_headers(),
                retry_options=self.retry_options,
                base_url=self.base_url,
            ),
        )

