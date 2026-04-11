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
        model=GlobalGemini(model="gemini-3-flash-preview"),
        ...
    )

Ref: https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/overview
"""

import os
from functools import cached_property
from typing import TYPE_CHECKING

from google.adk.models.google_llm import Gemini
from google.genai import types

if TYPE_CHECKING:
    from google.genai import Client


class GlobalGemini(Gemini):
    """Gemini model routed to the global endpoint for Gemini 3 access.

    On Agent Engine, vertexai is auto-initialized with the AE region
    (us-central1). The standard Gemini class creates Client() which
    inherits this location. GlobalGemini overrides api_client to create
    a Client with location='global' explicitly.
    """

    @cached_property
    def api_client(self) -> "Client":
        """Create a genai Client pointing to the global endpoint."""
        from google.genai import Client

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        return Client(
            vertexai=True,
            project=project,
            location="global",
            http_options=types.HttpOptions(
                headers=self._tracking_headers(),
                retry_options=self.retry_options,
                base_url=self.base_url,
            ),
        )
