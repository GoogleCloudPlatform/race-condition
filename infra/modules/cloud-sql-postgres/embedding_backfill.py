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

"""Backfill missing embeddings on the rules table via Vertex AI.

Invoked by the cloud-sql-postgres TF module's embedding_backfill
null_resource after seed_rules has been applied. Idempotent: only
touches rows where embedding IS NULL, so re-runs are cheap.

Required env vars:
  PROJECT_ID                     -- GCP project for Vertex AI
  GOOGLE_GENAI_USE_VERTEXAI=true -- forces google-genai to use Vertex
  GOOGLE_CLOUD_LOCATION          -- defaults to "global"
  DATABASE_HOST                  -- e.g. 127.0.0.1 (cloud-sql-proxy)
  DATABASE_PORT                  -- e.g. 15432
  DATABASE_USER                  -- defaults to "postgres"
  DATABASE_PASSWORD              -- the postgres user password
  DATABASE_NAME                  -- defaults to "postgres"
  EMBEDDING_MODEL                -- defaults to "gemini-embedding-001"
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

# Type-only imports: keep the static type contract while the runtime
# imports stay deferred (so this module is import-safe in test envs
# without asyncpg + google-genai installed).
if TYPE_CHECKING:
    import asyncpg as _asyncpg
    from google import genai as _genai


EMBED_DIMENSION = 3072


def _to_pgvector_text(vec: list[float]) -> str:
    """Format a Python embedding vector as pgvector's text input format.

    asyncpg cannot encode a Python list as TEXT, so the embedding must be
    serialized to pgvector's literal grammar ("[v1,v2,...]") and cast in
    SQL via `$1::vector`. Using repr(float(x)) preserves full precision
    and handles scientific notation correctly.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _client() -> _genai.Client:
    # Imported lazily so this module is import-safe in test environments
    # that don't have google-genai installed.
    from google import genai

    return genai.Client(
        vertexai=True,
        project=os.environ["PROJECT_ID"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
    )


async def _embed(client: _genai.Client, text: str) -> list[float]:
    model = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
    response = await client.aio.models.embed_content(
        model=model,
        contents=text,
        config={"output_dimensionality": EMBED_DIMENSION},
    )
    if not response.embeddings or response.embeddings[0].values is None:
        raise RuntimeError(f"Vertex AI returned no embedding for text: {text[:60]!r}")
    return list(response.embeddings[0].values)


async def main() -> int:
    # Imported lazily for the same reason as _client(): keeps module
    # import-safe in environments without asyncpg installed.
    import asyncpg

    conn = await asyncpg.connect(
        host=os.environ["DATABASE_HOST"],
        port=int(os.environ.get("DATABASE_PORT", "5432")),
        user=os.environ.get("DATABASE_USER", "postgres"),
        password=os.environ["DATABASE_PASSWORD"],
        database=os.environ.get("DATABASE_NAME", "postgres"),
    )

    try:
        # rules has no surrogate id column; the composite (source_file, chunk_id)
        # uniquely identifies each row. Use it for both selection and UPDATE.
        rows = await conn.fetch(
            "SELECT source_file, chunk_id, text FROM rules WHERE embedding IS NULL ORDER BY source_file, chunk_id"
        )
        if not rows:
            print("embedding_backfill: no rules with NULL embedding -- nothing to do.")
            return 0

        client = _client()
        print(f"embedding_backfill: backfilling {len(rows)} rule(s) via Vertex AI...")

        for row in rows:
            vec = await _embed(client, row["text"])
            await conn.execute(
                "UPDATE rules SET embedding = $1::vector WHERE source_file = $2 AND chunk_id = $3",
                _to_pgvector_text(vec),
                row["source_file"],
                row["chunk_id"],
            )
            print(f"  - updated rule {row['source_file']}#{row['chunk_id']}")

        print(f"embedding_backfill: done ({len(rows)} row(s) updated).")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
