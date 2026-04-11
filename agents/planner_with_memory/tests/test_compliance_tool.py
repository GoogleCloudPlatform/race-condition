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

"""Tests for the get_local_and_traffic_rules tool."""

import pytest

from agents.planner_with_memory.memory.tools import get_local_and_traffic_rules


class TestGetLocalAndTrafficRules:
    """Tests for the traffic rules lookup tool (AlloyDB implementation)."""

    def _make_mock_conn(self, rows):
        """Return a mock asyncpg connection that returns `rows` from fetch()."""
        from unittest.mock import AsyncMock, MagicMock

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()
        return mock_conn

    @pytest.mark.asyncio
    async def test_returns_rules_list(self):
        """Tool returns a list of rules with city and text keys."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [
            {"city": "Las Vegas", "text": "Road closure permits required."},
            {"city": "Las Vegas", "text": "Noise ordinance applies after 10 PM."},
        ]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            result = await get_local_and_traffic_rules(query="road closure permits", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert isinstance(result["rules"], list)
        assert len(result["rules"]) == 2
        # backward compat: regulations key must mirror rules
        assert result["regulations"] == result["rules"]

    @pytest.mark.asyncio
    async def test_rules_have_city_and_text(self):
        """Each rule entry has city and text fields."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [{"city": "Las Vegas", "text": "Some rule."}]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            result = await get_local_and_traffic_rules(query="permits", tool_context=mock_ctx)

        for reg in result["rules"]:
            assert "city" in reg, "rule missing 'city'"
            assert "text" in reg, "rule missing 'text'"

    @pytest.mark.asyncio
    async def test_missing_alloydb_host_returns_error(self):
        """Without ALLOYDB_HOST configured, tool returns an error dict."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            result = await get_local_and_traffic_rules(query="noise ordinance", tool_context=mock_ctx)

        assert result["status"] == "error"
        assert "ALLOYDB_HOST" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_dict_for_a2a_compliance(self):
        """Tool must return a dict for A2A JSON serialisation."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [{"city": "Las Vegas", "text": "Any rule."}]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            result = await get_local_and_traffic_rules(query="anything", tool_context=mock_ctx)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_postgres_mode_returns_sample_chunks(self):
        """When USE_ALLOYDB=false, tool returns 2 sample chunks instead of an error.

        The local Postgres container lacks the ai.embedding() extension.
        Instead of failing, the tool must degrade gracefully with sample data.
        """
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {"USE_ALLOYDB": "false", "ALLOYDB_HOST": "127.0.0.1"}):
            result = await get_local_and_traffic_rules(query="road closure permits", tool_context=mock_ctx)

        assert result["status"] == "success", f"Expected success, got: {result}"
        assert isinstance(result["rules"], list)
        assert len(result["rules"]) >= 2
        assert result["regulations"] == result["rules"]
        for reg in result["rules"]:
            assert "city" in reg
            assert "text" in reg

    @pytest.mark.asyncio
    async def test_ai_embedding_error_returns_sample_chunks(self):
        """When ai.embedding() is unavailable, tool returns 2 sample chunks.

        This can happen if USE_ALLOYDB=true but pointed at a plain Postgres
        instance that lacks the AlloyDB AI extension.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("function ai.embedding(unknown, text) does not exist"))
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict(
                "os.environ",
                {"USE_ALLOYDB": "true", "ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"},
            ),
        ):
            result = await get_local_and_traffic_rules(query="noise ordinance", tool_context=mock_ctx)

        assert result["status"] == "success", f"Expected success, got: {result}"
        assert isinstance(result["rules"], list)
        assert len(result["rules"]) >= 2
        assert result["regulations"] == result["rules"]
        for reg in result["rules"]:
            assert "city" in reg
            assert "text" in reg


def test_compliance_is_mandatory_workflow_step():
    """get_local_and_traffic_rules must be a mandatory step in the Memory Workflow."""
    from agents.planner_with_memory.prompts import MEMORY_SYSTEM_INSTRUCTION

    # Find the Workflow section and check ordering within it
    instruction = MEMORY_SYSTEM_INSTRUCTION
    workflow_start = instruction.find("# Workflow")
    assert workflow_start != -1, "Workflow section must exist"
    workflow_section = instruction[workflow_start:]

    compliance_pos = workflow_section.find("get_local_and_traffic_rules")
    route_pos = workflow_section.find("plan_marathon_route")
    assert compliance_pos != -1
    assert route_pos != -1, "plan_marathon_route must appear in the Memory Workflow"
    assert compliance_pos < route_pos


# ========================================================================================
# Simulation History Tools
# ========================================================================================


class TestStoreSimulationSummary:
    """Tests for the store_simulation_summary tool."""

    @pytest.mark.asyncio
    async def test_stores_summary_and_returns_id(self):
        """Successful store returns a summary_id."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon in Las Vegas",
                summary="Planned a 26.2-mile marathon in Las Vegas. 98% completion rate.",
                tool_context=mock_ctx,
                city="Las Vegas",
            )

        assert result["status"] == "success"
        assert "summary_id" in result
        assert isinstance(result["summary_id"], str)

    @pytest.mark.asyncio
    async def test_missing_host_returns_error(self):
        """Without ALLOYDB_HOST, tool returns an error dict."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon",
                summary="Some summary",
                tool_context=mock_ctx,
            )

        assert result["status"] == "error"
        assert "ALLOYDB_HOST" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_dict_for_a2a_compliance(self):
        """Tool must return a dict for A2A JSON serialisation."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon",
                summary="Summary text",
                tool_context=mock_ctx,
            )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_local_postgres_mode_skips_gracefully(self):
        """When USE_ALLOYDB=false, tool skips persist and returns success."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {"USE_ALLOYDB": "false", "ALLOYDB_HOST": "127.0.0.1"}):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon in Las Vegas for 1000 runners and two camels",
                summary="Planned route through Mandalay Bay. 95% completion. Dehydrated runners",
                tool_context=mock_ctx,
                city="Las Vegas",
            )

        assert result["status"] == "success"
        assert result["summary_id"] == "local-mode-skipped"
        assert "note" in result


class TestRecallPastSimulations:
    """Tests for the recall_past_simulations tool."""

    def _make_mock_conn(self, rows):
        from unittest.mock import AsyncMock, MagicMock

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()
        return mock_conn

    @pytest.mark.asyncio
    async def test_returns_simulations_text(self):
        """Tool returns past simulations as both a structured list and message text."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [
            {
                "city": "Las Vegas",
                "prompt": "Plan a marathon in Las Vegas",
                "summary": "Planned 26.2-mile route. 98% completion.",
                "sim_result": {"status": "completed"},
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test", "USE_ALLOYDB": "true"}),
        ):
            from agents.planner_with_memory.memory.tools import recall_past_simulations

            result = await recall_past_simulations(query="marathon in Las Vegas", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 1

        # Structured list of simulations
        assert isinstance(result["simulations"], list)
        assert len(result["simulations"]) == 1
        assert result["simulations"][0]["city"] == "Las Vegas"

        # Human-readable message text
        assert isinstance(result["message"], str)
        assert "Las Vegas" in result["message"]

    @pytest.mark.asyncio
    async def test_local_postgres_mode_returns_empty(self):
        """When USE_ALLOYDB=false, tool returns empty list gracefully."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {"USE_ALLOYDB": "false", "ALLOYDB_HOST": "127.0.0.1"}):
            from agents.planner_with_memory.memory.tools import recall_past_simulations

            result = await recall_past_simulations(query="marathon in Chicago", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["simulations"] == []

    @pytest.mark.asyncio
    async def test_ai_embedding_error_returns_empty(self):
        """When ai.embedding() is unavailable, tool returns empty list."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("function ai.embedding(unknown, text) does not exist"))
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", {"USE_ALLOYDB": "true", "ALLOYDB_HOST": "fake-host", "ALLOYDB_PASSWORD": "test"}),
        ):
            from agents.planner_with_memory.memory.tools import recall_past_simulations

            result = await recall_past_simulations(query="marathon in NYC", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["simulations"] == []
