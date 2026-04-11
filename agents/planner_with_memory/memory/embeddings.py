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

"""Vertex AI embedding helper for OSS deployments without AlloyDB ai.embedding().

Production AlloyDB uses ``CALL ai.initialize_embeddings(...)`` to populate
the ``embedding`` column automatically on INSERT, and ``ai.embedding(...)``
to embed query strings at SELECT time. Cloud SQL Postgres has neither
extension, so OSS deployments must compute embeddings client-side.

The ``compute_embedding`` helper does that via google-genai (Vertex AI).
Selectable via the ``EMBEDDING_BACKEND`` env var on the calling code:
``vertex_ai`` enables this path, ``alloydb_ai`` (default) keeps the
existing AlloyDB-trigger path. ``EMBEDDING_BACKEND`` is auto-derived to
``vertex_ai`` when ``USE_ALLOYDB=false`` so local-dev workflows need no
extra configuration.
"""

from __future__ import annotations

import os
from functools import lru_cache

from google import genai


@lru_cache(maxsize=1)
def _get_genai_client() -> genai.Client:
    """Return a process-global google-genai client.

    Resolves the project from ``GOOGLE_CLOUD_PROJECT`` (codebase convention) or
    ``PROJECT_ID`` (OSS deploy convention, set by Cloud Build). When a project
    is available, uses Vertex AI. Otherwise falls back to API-key auth
    (local dev with ``GEMINI_API_KEY``).
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
    if project:
        return genai.Client(
            vertexai=True,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))


async def compute_embedding(text: str, *, dimension: int = 3072) -> list[float]:
    """Compute a 3072-dim embedding for ``text`` via Vertex AI / Gemini.

    Raises whatever the underlying client raises; callers decide retry/fallback
    policy. Used when AlloyDB's ``ai.embedding()`` extension is unavailable
    (e.g. OSS deploys against Cloud SQL Postgres).

    Args:
        text: The text to embed (a query string for similarity search, or
            the document text being inserted).
        dimension: Output vector dimension. Default 3072 matches the
            ``VECTOR(3072)`` column in ``planner_with_memory`` schemas.

    Returns:
        The embedding as a list of floats, length ``dimension``.
    """
    client = _get_genai_client()
    model = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
    response = await client.aio.models.embed_content(
        model=model,
        contents=text,
        config={"output_dimensionality": dimension},
    )
    if not response.embeddings:
        raise RuntimeError(f"embed_content returned no embeddings for model={model}")
    values = response.embeddings[0].values
    if values is None:
        raise RuntimeError(f"embed_content returned embedding with no values for model={model}")
    return list(values)
