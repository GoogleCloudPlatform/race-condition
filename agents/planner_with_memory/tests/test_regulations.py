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

"""Tests for AlloyDB regulation assets (LEGISLATION.txt, seed SQL, MCP tool).

These tests cover three layers without requiring a live AlloyDB connection:
1. Static data quality — LEGISLATION.txt and seed_regulations.sql
2. Seed script logic — seed_routes.py against a mocked asyncpg connection
3. MCP tool wiring — that adk_tools.py registers the MCP toolset correctly
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Paths to static assets
_ALLOYDB_DIR = Path(__file__).parent.parent / "alloydb"
_LEGISLATION_TXT = _ALLOYDB_DIR / "LEGISLATION.txt"
_SEED_REGULATIONS_SQL = _ALLOYDB_DIR / "seed_rules.sql"
_SCHEMA_SQL = _ALLOYDB_DIR / "schema.sql"


# ---------------------------------------------------------------------------
# 1. Static asset quality tests
# ---------------------------------------------------------------------------


class TestLegislationTxt:
    """LEGISLATION.txt must exist and contain well-formed regulation chunks."""

    def test_file_exists(self):
        assert _LEGISLATION_TXT.exists(), "LEGISLATION.txt missing from alloydb/"

    def test_file_not_empty(self):
        content = _LEGISLATION_TXT.read_text()
        assert len(content.strip()) > 0

    def test_contains_las_vegas_content(self):
        content = _LEGISLATION_TXT.read_text()
        assert "Las Vegas" in content or "LAS VEGAS" in content

    def test_contains_nevada_content(self):
        content = _LEGISLATION_TXT.read_text()
        assert "Nevada" in content or "NEVADA" in content

    def test_no_placeholder_text(self):
        """Ensure no un-substituted template placeholders remain."""
        content = _LEGISLATION_TXT.read_text()
        assert "TODO" not in content
        assert "PLACEHOLDER" not in content
        assert "PROJECT_ID" not in content


class TestSeedRegulationsSQL:
    """seed_regulations.sql must contain valid, idempotent INSERT statements."""

    def test_file_exists(self):
        assert _SEED_REGULATIONS_SQL.exists()

    def test_has_insert_statement(self):
        sql = _SEED_REGULATIONS_SQL.read_text()
        assert re.search(r"\bINSERT\b", sql, re.IGNORECASE)

    def test_targets_rules_table(self):
        sql = _SEED_REGULATIONS_SQL.read_text()
        assert "rules" in sql

    def test_is_idempotent(self):
        """Must use ON CONFLICT to be safely re-applied."""
        sql = _SEED_REGULATIONS_SQL.read_text()
        assert "ON CONFLICT" in sql.upper()

    def test_has_three_chunks(self):
        """Expect exactly 3 regulation chunks in the seed file."""
        sql = _SEED_REGULATIONS_SQL.read_text()
        # Each chunk starts with ('LEGISLATION.txt',
        matches = re.findall(r"\('LEGISLATION\.txt'", sql)
        assert len(matches) == 3, f"Expected 3 chunks, found {len(matches)}"

    def test_cities_present(self):
        sql = _SEED_REGULATIONS_SQL.read_text()
        assert "'Las Vegas'" in sql or "Las Vegas" in sql
        assert "'Nevada'" in sql or "Nevada" in sql


class TestSchemaSql:
    """schema.sql must define all three required tables."""

    def test_file_exists(self):
        assert _SCHEMA_SQL.exists()

    def test_defines_rules_table(self):
        sql = _SCHEMA_SQL.read_text()
        assert "rules" in sql
        # Expect the vector column for RAG
        assert "embedding" in sql
        assert "VECTOR" in sql.upper()

    def test_defines_planned_routes_table(self):
        sql = _SCHEMA_SQL.read_text()
        assert "planned_routes" in sql

    def test_defines_simulation_records_table(self):
        sql = _SCHEMA_SQL.read_text()
        assert "simulation_records" in sql

    def test_planned_routes_has_jsonb_columns(self):
        sql = _SCHEMA_SQL.read_text()
        assert "JSONB" in sql.upper()

    def test_foreign_key_from_simulations_to_routes(self):
        sql = _SCHEMA_SQL.read_text()
        assert "REFERENCES planned_routes" in sql

    def test_idempotent_create(self):
        sql = _SCHEMA_SQL.read_text()
        assert "IF NOT EXISTS" in sql.upper()


# ---------------------------------------------------------------------------
# 2. Seed script logic (mocked asyncpg)
# ---------------------------------------------------------------------------


class TestSeedRoutesScript:
    """seed_routes.py inserts JSON seed files into AlloyDB idempotently."""

    @pytest.mark.asyncio
    async def test_seeds_are_inserted(self, tmp_path):
        """Each *.json file in memory/seeds/ should generate one INSERT."""
        from agents.planner_with_memory.alloydb import seed_routes as seed_module

        # Build a minimal mock connection
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.close = AsyncMock()

        with (
            patch("asyncpg.connect", return_value=mock_conn),
            patch(
                "agents.planner_with_memory.memory.store_alloydb._get_dsn",
                return_value="postgresql://fake",
            ),
        ):
            loaded = await seed_module.seed_routes()

        # We have 4 seed JSON files (01..04)
        assert loaded == 4
        assert mock_conn.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_upserts_existing_rows(self):
        """ON CONFLICT DO UPDATE: existing rows are updated and counted."""
        from agents.planner_with_memory.alloydb import seed_routes as seed_module

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")  # upsert → always 1
        mock_conn.close = AsyncMock()

        with (
            patch("asyncpg.connect", return_value=mock_conn),
            patch(
                "agents.planner_with_memory.memory.store_alloydb._get_dsn",
                return_value="postgresql://fake",
            ),
        ):
            loaded = await seed_module.seed_routes()

        assert loaded == 4  # all 4 seed files are upserted

    @pytest.mark.asyncio
    async def test_connection_is_always_closed(self):
        """Close must be called even if an INSERT raises."""
        from agents.planner_with_memory.alloydb import seed_routes as seed_module

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_conn.close = AsyncMock()

        with (
            patch("asyncpg.connect", return_value=mock_conn),
            patch(
                "agents.planner_with_memory.memory.store_alloydb._get_dsn",
                return_value="postgresql://fake",
            ),
        ):
            # Should not raise — errors are caught per-file
            loaded = await seed_module.seed_routes()

        mock_conn.close.assert_called_once()
        assert loaded == 0


# ---------------------------------------------------------------------------
# 3. MCP tool wiring (adk_tools.py)
# ---------------------------------------------------------------------------


class TestGetToolsInterface:
    """adk_tools.get_tools() must match the dev-branch interface.

    Expected: get_eval_tools() + get_memory_tools() — no separate MCP/RAG args.
    The 6th memory tool must be get_local_and_traffic_rules.
    """

    def test_get_tools_returns_list(self):
        from agents.planner_with_memory import adk_tools

        with (
            patch.object(adk_tools, "get_eval_tools", return_value=[]),
            patch.object(adk_tools, "get_memory_tools", return_value=[MagicMock()]),
        ):
            tools = adk_tools.get_tools()

        assert isinstance(tools, list)

    def test_get_tools_includes_eval_and_memory(self):
        """get_tools() = get_eval_tools() + get_memory_tools() — nothing more."""
        from agents.planner_with_memory import adk_tools

        eval_tool = MagicMock(name="eval_tool")
        memory_tool = MagicMock(name="memory_tool")

        with (
            patch.object(adk_tools, "get_eval_tools", return_value=[eval_tool]),
            patch.object(adk_tools, "get_memory_tools", return_value=[memory_tool]),
        ):
            tools = adk_tools.get_tools()

        assert eval_tool in tools
        assert memory_tool in tools
        assert len(tools) == 2

    def test_get_memory_tools_returns_nine_tools(self):
        """get_memory_tools() must return exactly 9 FunctionTools."""
        from agents.planner_with_memory.memory.adk_tools import get_memory_tools

        tools = get_memory_tools()
        assert len(tools) == 9

    def test_get_memory_tools_names(self):
        """All 9 expected tool names must be present."""
        from agents.planner_with_memory.memory.adk_tools import get_memory_tools

        names = {t.name for t in get_memory_tools()}
        expected = {
            "store_route",
            "record_simulation",
            "recall_routes",
            "get_route",
            "get_planned_routes_data",
            "get_best_route",
            "get_local_and_traffic_rules",
            "store_simulation_summary",
            "recall_past_simulations",
        }
        assert names == expected
