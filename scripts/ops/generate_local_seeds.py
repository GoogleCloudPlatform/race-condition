#!/usr/bin/env python3
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

"""Generate seed_local.sql with pre-computed embeddings for local Postgres.

Reads regulation text chunks from seed_regulations.sql and route data from
the JSON seed files, calls Vertex AI to generate 3072-dim embeddings for
regulations, and writes an idempotent seed_local.sql file.

Usage:
    uv run python scripts/ops/generate_local_seeds.py
    uv run python scripts/ops/generate_local_seeds.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ALLOYDB_DIR = _REPO_ROOT / "agents" / "planner_with_memory" / "alloydb"
_SEEDS_DIR = _REPO_ROOT / "agents" / "planner_with_memory" / "memory" / "seeds"
_SEED_REGULATIONS_SQL = _ALLOYDB_DIR / "seed_rules.sql"
_OUTPUT_FILE = _ALLOYDB_DIR / "seed_local.sql"

_LICENSE_HEADER = """\
-- Copyright 2026 Google LLC
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.
"""


def _parse_regulation_chunks(sql_text: str) -> list[dict]:
    """Extract (source_file, chunk_id, city, text) tuples from seed SQL."""
    # Match each VALUES tuple: ('LEGISLATION.txt', N, 'City', 'text...')
    pattern = re.compile(
        r"\('(LEGISLATION\.txt)',\s*(\d+),\s*'([^']+)',\s*\n'((?:[^']|'')*?)'\)",
        re.DOTALL,
    )
    chunks = []
    for m in pattern.finditer(sql_text):
        source_file = m.group(1)
        chunk_id = int(m.group(2))
        city = m.group(3)
        text = m.group(4).replace("''", "'")  # un-escape SQL single quotes
        chunks.append(
            {
                "source_file": source_file,
                "chunk_id": chunk_id,
                "city": city,
                "text": text,
            }
        )
    return chunks


def _generate_embeddings(texts: list[str], project: str) -> list[list[float]]:
    """Call Vertex AI to generate 3072-dim embeddings for each text."""
    from google import genai

    client = genai.Client(vertexai=True, project=project, location="global")
    embeddings = []
    for text in texts:
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
        )
        embeddings.append(response.embeddings[0].values)
    return embeddings


def _sql_escape(text: str) -> str:
    """Escape a string for SQL single-quoted literal."""
    return text.replace("'", "''")


def _format_vector(values: list[float]) -> str:
    """Format a list of floats as a Postgres vector literal."""
    inner = ",".join(f"{v}" for v in values)
    return f"'[{inner}]'::vector"


def _build_regulation_inserts(chunks: list[dict], embeddings: list[list[float]] | None) -> str:
    """Build INSERT statements for regulation chunks."""
    lines = [
        "-- Regulation seed data with pre-computed embeddings.",
        "-- Source: agents/planner_with_memory/alloydb/seed_rules.sql",
        "",
    ]
    for i, chunk in enumerate(chunks):
        source = _sql_escape(chunk["source_file"])
        city = _sql_escape(chunk["city"])
        text = _sql_escape(chunk["text"])

        if embeddings and i < len(embeddings):
            embedding_expr = _format_vector(embeddings[i])
            lines.append(
                f"INSERT INTO rules (source_file, chunk_id, city, text, embedding) VALUES\n"
                f"('{source}', {chunk['chunk_id']}, '{city}',\n"
                f"'{text}',\n"
                f"{embedding_expr})\n"
                f"ON CONFLICT DO NOTHING;"
            )
        else:
            lines.append(
                f"INSERT INTO rules (source_file, chunk_id, city, text) VALUES\n"
                f"('{source}', {chunk['chunk_id']}, '{city}',\n"
                f"'{text}')\n"
                f"ON CONFLICT DO NOTHING;"
            )
        lines.append("")
    return "\n".join(lines)


def _build_route_inserts() -> str:
    """Build INSERT statements for route seed data from JSON files."""
    lines = [
        "-- Route seed data converted from JSON seed files.",
        "-- Source: agents/planner_with_memory/memory/seeds/*.json",
        "",
    ]
    for filepath in sorted(_SEEDS_DIR.glob("*.json")):
        data = json.loads(filepath.read_text())
        route_id = _sql_escape(data["route_id"])
        created_at_str = data["created_at"]
        created_at = datetime.fromisoformat(created_at_str)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Inject top-level name into route_data (matching seed_routes.py pattern)
        route_data = data["route_data"]
        if isinstance(route_data, dict) and "name" not in route_data:
            seed_name = data.get("name")
            if seed_name:
                route_data["name"] = seed_name

        route_data_json = _sql_escape(json.dumps(route_data, separators=(",", ":")))
        eval_score = data.get("evaluation_score")
        eval_result = data.get("evaluation_result")

        eval_score_sql = str(eval_score) if eval_score is not None else "NULL"
        if eval_result is not None:
            eval_result_sql = f"'{_sql_escape(json.dumps(eval_result, separators=(',', ':')))}'::jsonb"
        else:
            eval_result_sql = "NULL"

        lines.append(
            f"INSERT INTO planned_routes (route_id, route_data, created_at, eval_score, eval_result) VALUES\n"
            f"('{route_id}', '{route_data_json}'::jsonb, '{created_at.isoformat()}', {eval_score_sql}, {eval_result_sql})\n"
            f"ON CONFLICT (route_id) DO UPDATE SET\n"
            f"    route_data = EXCLUDED.route_data,\n"
            f"    eval_score = EXCLUDED.eval_score,\n"
            f"    eval_result = EXCLUDED.eval_result;"
        )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate seed_local.sql with pre-computed embeddings.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated SQL to stdout without writing to file.",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (regulations will have NULL embeddings).",
    )
    args = parser.parse_args()

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project and not args.skip_embeddings:
        print(
            "ERROR: GOOGLE_CLOUD_PROJECT env var is required (or use --skip-embeddings).",
            file=sys.stderr,
        )
        sys.exit(1)

    # 1. Parse regulation chunks
    sql_text = _SEED_REGULATIONS_SQL.read_text()
    chunks = _parse_regulation_chunks(sql_text)
    if not chunks:
        print("ERROR: No regulation chunks found in seed_regulations.sql", file=sys.stderr)
        sys.exit(1)
    print(f"Parsed {len(chunks)} regulation chunks.", file=sys.stderr)

    # 2. Generate embeddings (unless skipped)
    embeddings = None
    if not args.skip_embeddings:
        print("Generating embeddings via Vertex AI...", file=sys.stderr)
        texts = [c["text"] for c in chunks]
        embeddings = _generate_embeddings(texts, project)
        print(f"Generated {len(embeddings)} embeddings ({len(embeddings[0])} dims each).", file=sys.stderr)
    else:
        print("Skipping embedding generation (--skip-embeddings).", file=sys.stderr)

    # 3. Build SQL
    parts = [
        _LICENSE_HEADER,
        "-- Local seed data for the planner_with_memory Postgres container.",
        "-- Auto-generated by scripts/ops/generate_local_seeds.py",
        "-- Run AFTER schema_local.sql (01_schema.sql) has been applied.",
        "",
        "-- ============================================================",
        "-- 1. REGULATIONS",
        "-- ============================================================",
        "",
        _build_regulation_inserts(chunks, embeddings),
        "-- ============================================================",
        "-- 2. PLANNED ROUTES",
        "-- ============================================================",
        "",
        _build_route_inserts(),
    ]
    sql_output = "\n".join(parts) + "\n"

    # 4. Output
    if args.dry_run:
        print(sql_output)
    else:
        _OUTPUT_FILE.write_text(sql_output)
        print(f"Wrote {_OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
