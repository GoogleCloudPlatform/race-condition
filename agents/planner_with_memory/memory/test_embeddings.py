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

"""Tests for the Vertex AI embedding fallback used by OSS deployments.

OSS deploys against Cloud SQL Postgres which has no AlloyDB
``ai.embedding()`` extension. The compute_embedding helper computes
embeddings client-side via google-genai (Vertex AI) so semantic
recall works in OSS the same way it does in dev/prod AlloyDB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.planner_with_memory.memory import embeddings


@pytest.mark.asyncio
async def test_compute_embedding_returns_3072_dim_vector() -> None:
    """Vertex AI embedding helper returns the right-shaped vector."""
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(
        return_value=MagicMock(embeddings=[MagicMock(values=[0.1] * 3072)])
    )
    with patch.object(embeddings, "_get_genai_client", return_value=fake_client):
        vec = await embeddings.compute_embedding("Plan a marathon in Las Vegas")

    assert isinstance(vec, list)
    assert len(vec) == 3072
    assert all(isinstance(v, float) for v in vec)


@pytest.mark.asyncio
async def test_compute_embedding_uses_configured_model(monkeypatch) -> None:
    """Honors EMBEDDING_MODEL env var; defaults to gemini-embedding-001."""
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(
        return_value=MagicMock(embeddings=[MagicMock(values=[0.0] * 3072)])
    )
    with patch.object(embeddings, "_get_genai_client", return_value=fake_client):
        await embeddings.compute_embedding("hello")

    fake_client.aio.models.embed_content.assert_awaited_once()
    await_args = fake_client.aio.models.embed_content.await_args
    assert await_args is not None
    assert await_args.kwargs["model"] == "gemini-embedding-001"


@pytest.mark.asyncio
async def test_compute_embedding_passes_dimension_in_config() -> None:
    """The dimension argument flows through as EmbedContentConfig.output_dimensionality."""
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(return_value=MagicMock(embeddings=[MagicMock(values=[0.0] * 768)]))
    with patch.object(embeddings, "_get_genai_client", return_value=fake_client):
        await embeddings.compute_embedding("hello", dimension=768)

    await_args = fake_client.aio.models.embed_content.await_args
    assert await_args is not None
    config = await_args.kwargs["config"]
    # Config can be passed as dict or EmbedContentConfig — accept either.
    if hasattr(config, "output_dimensionality"):
        assert config.output_dimensionality == 768
    else:
        assert config["output_dimensionality"] == 768


@pytest.mark.asyncio
async def test_compute_embedding_raises_on_api_failure() -> None:
    """Caller decides how to handle Vertex AI failures (no silent fallback)."""
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("quota exceeded"))
    with patch.object(embeddings, "_get_genai_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="quota exceeded"):
            await embeddings.compute_embedding("hello")
