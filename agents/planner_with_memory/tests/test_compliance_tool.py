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
        for reg in result["rules"]:
            assert "city" in reg
            assert "text" in reg

    @pytest.mark.asyncio
    async def test_local_postgres_falls_back_to_samples_when_embedding_fails(self):
        """USE_ALLOYDB=false (auto-derives EMBEDDING_BACKEND=vertex_ai): when
        compute_embedding fails, gracefully fall back to sample chunks rather
        than surfacing an error to the agent."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_ctx = MagicMock()

        with (
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(side_effect=RuntimeError("Vertex AI unavailable")),
            ),
            patch.dict("os.environ", {"USE_ALLOYDB": "false", "ALLOYDB_HOST": "127.0.0.1"}),
        ):
            result = await get_local_and_traffic_rules(query="road permits", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert len(result["rules"]) >= 2  # Sample rules


def test_compliance_is_mandatory_workflow_step():
    """get_local_and_traffic_rules must be a mandatory step in the Memory Workflow."""
    from agents.planner_with_memory.prompts import PLANNER_WITH_MEMORY

    # Find the Workflow section and check ordering within it
    instruction = PLANNER_WITH_MEMORY.build()
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

        # USE_ALLOYDB pinned to "true" defends against test pollution from
        # earlier tests that flip USE_ALLOYDB=false. With USE_ALLOYDB unset
        # or false, _resolve_embedding_backend() returns "vertex_ai" which
        # makes the tool reach for the real GenAI client and fail (the test
        # only mocks asyncpg.connect, not the embedding service).
        env_patch = {
            "ALLOYDB_HOST": "fake-host",
            "ALLOYDB_PASSWORD": "test",
            "USE_ALLOYDB": "true",
        }
        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch.dict("os.environ", env_patch),
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
    async def test_local_postgres_mode_persists_to_db(self):
        """USE_ALLOYDB=false (auto-derives EMBEDDING_BACKEND=vertex_ai): summaries
        are persisted to local Postgres with a client-computed embedding."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=[0.1] * 3072),
            ),
            patch.dict("os.environ", {"USE_ALLOYDB": "false", "ALLOYDB_HOST": "127.0.0.1"}),
        ):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon in Las Vegas",
                summary="Planned 26.2-mile route. 98% completion.",
                tool_context=mock_ctx,
                city="Las Vegas",
            )

        assert result["status"] == "success"
        assert result["summary_id"] != "local-mode-skipped"
        assert isinstance(result["summary_id"], str)
        # Verify it actually called execute (persisted to DB)
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_local_postgres_without_host_returns_error(self):
        """Without ALLOYDB_HOST set, tool returns error even in local mode."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock()
        with patch.dict("os.environ", {"USE_ALLOYDB": "false"}, clear=True):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon",
                summary="Summary",
                tool_context=mock_ctx,
            )

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_vertex_ai_backend_computes_and_inserts_embedding(self):
        """When EMBEDDING_BACKEND=vertex_ai, embedding is computed client-side and INSERTed."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()
        mock_ctx = MagicMock()
        fake_vec = [0.1] * 3072

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=fake_vec),
            ) as mock_embed,
            patch.dict(
                "os.environ",
                {
                    "ALLOYDB_HOST": "fake-host",
                    "ALLOYDB_PASSWORD": "test",
                    "USE_ALLOYDB": "true",
                    "EMBEDDING_BACKEND": "vertex_ai",
                },
            ),
        ):
            from agents.planner_with_memory.memory.tools import store_simulation_summary

            result = await store_simulation_summary(
                prompt="Plan a marathon",
                summary="Marathon summary text for embedding",
                tool_context=mock_ctx,
                city="Las Vegas",
            )

        assert result["status"] == "success"
        # Embedding helper was called with the summary text.
        mock_embed.assert_awaited_once_with("Marathon summary text for embedding")
        # The INSERT statement included an "embedding" column.
        execute_call = mock_conn.execute.await_args
        assert execute_call is not None
        sql = execute_call.args[0]
        assert "embedding" in sql.lower(), f"INSERT SQL should include embedding column: {sql}"
        # The embedding vector was passed as a parameter.
        expected_pgvec = "[" + ",".join(str(v) for v in fake_vec) + "]"
        assert expected_pgvec in execute_call.args, "Embedding vector should be passed as pgvector text literal"


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

    @pytest.mark.asyncio
    async def test_vertex_ai_backend_embeds_query_and_uses_vector_param(self):
        """EMBEDDING_BACKEND=vertex_ai: query is embedded client-side, SQL uses $N::vector."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = []  # empty result set is fine; we're asserting the call shape
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()
        fake_vec = [0.2] * 3072

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=fake_vec),
            ) as mock_embed,
            patch.dict(
                "os.environ",
                {
                    "ALLOYDB_HOST": "fake-host",
                    "ALLOYDB_PASSWORD": "test",
                    "USE_ALLOYDB": "true",
                    "EMBEDDING_BACKEND": "vertex_ai",
                },
            ),
        ):
            from agents.planner_with_memory.memory.tools import recall_past_simulations

            result = await recall_past_simulations(query="marathon in Las Vegas", tool_context=mock_ctx)

        assert result["status"] == "success"
        # Embedding helper was called with the query.
        mock_embed.assert_awaited_once_with("marathon in Las Vegas")
        # SQL must use $N::vector and must NOT call ai.embedding()
        fetch_call = mock_conn.fetch.await_args
        assert fetch_call is not None
        sql = fetch_call.args[0]
        assert "::vector" in sql, f"SQL should use ::vector cast: {sql}"
        assert "ai.embedding" not in sql, f"vertex_ai backend must not call ai.embedding(): {sql}"
        # The embedding vector was passed as a parameter.
        expected_pgvec = "[" + ",".join(str(v) for v in fake_vec) + "]"
        assert expected_pgvec in fetch_call.args, "Embedding vector should be passed as pgvector text literal"

    @pytest.mark.asyncio
    async def test_vertex_ai_backend_bypasses_use_alloydb_false_shortcircuit(self):
        """EMBEDDING_BACKEND=vertex_ai overrides USE_ALLOYDB=false; query DB instead of returning sample/empty."""
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [
            {
                "city": "Las Vegas",
                "prompt": "Plan a marathon in Las Vegas",
                "summary": "Real DB hit, not the sample short-circuit.",
                "sim_result": {"status": "completed"},
                "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
        ]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=[0.0] * 3072),
            ),
            patch.dict(
                "os.environ",
                {
                    "ALLOYDB_HOST": "fake-host",
                    "ALLOYDB_PASSWORD": "test",
                    "USE_ALLOYDB": "false",  # would normally short-circuit to empty
                    "EMBEDDING_BACKEND": "vertex_ai",
                },
            ),
        ):
            from agents.planner_with_memory.memory.tools import recall_past_simulations

            result = await recall_past_simulations(query="marathon", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["count"] == 1, "vertex_ai backend must hit the DB, not the empty short-circuit"
        assert result["simulations"][0]["summary"] == "Real DB hit, not the sample short-circuit."


class TestGetLocalAndTrafficRulesVertexAIBackend:
    """Tests for the vertex_ai backend path of get_local_and_traffic_rules."""

    def _make_mock_conn(self, rows):
        from unittest.mock import AsyncMock, MagicMock

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_conn.close = AsyncMock()
        return mock_conn

    @pytest.mark.asyncio
    async def test_vertex_ai_backend_embeds_query_and_uses_vector_param(self):
        """EMBEDDING_BACKEND=vertex_ai: query is embedded client-side, SQL uses $N::vector."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [{"city": "Las Vegas", "text": "Real DB rule."}]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()
        fake_vec = [0.3] * 3072

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=fake_vec),
            ) as mock_embed,
            patch.dict(
                "os.environ",
                {
                    "ALLOYDB_HOST": "fake-host",
                    "ALLOYDB_PASSWORD": "test",
                    "USE_ALLOYDB": "true",
                    "EMBEDDING_BACKEND": "vertex_ai",
                },
            ),
        ):
            result = await get_local_and_traffic_rules(query="noise ordinance", tool_context=mock_ctx)

        assert result["status"] == "success"
        mock_embed.assert_awaited_once_with("noise ordinance")
        fetch_call = mock_conn.fetch.await_args
        assert fetch_call is not None
        sql = fetch_call.args[0]
        assert "::vector" in sql, f"SQL should use ::vector cast: {sql}"
        assert "ai.embedding" not in sql, f"vertex_ai backend must not call ai.embedding(): {sql}"
        expected_pgvec = "[" + ",".join(str(v) for v in fake_vec) + "]"
        assert expected_pgvec in fetch_call.args, "Embedding vector should be passed as pgvector text literal"
        # Real DB row should be returned, not the static SAMPLE_RULES.
        assert result["rules"] == [{"city": "Las Vegas", "text": "Real DB rule."}]

    @pytest.mark.asyncio
    async def test_vertex_ai_backend_bypasses_use_alloydb_false_shortcircuit(self):
        """EMBEDDING_BACKEND=vertex_ai overrides USE_ALLOYDB=false; query DB instead of sample data."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_rows = [{"city": "Las Vegas", "text": "Real DB rule, not sample."}]
        mock_conn = self._make_mock_conn(fake_rows)
        mock_ctx = MagicMock()

        with (
            patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
            patch(
                "agents.planner_with_memory.memory.embeddings.compute_embedding",
                AsyncMock(return_value=[0.0] * 3072),
            ),
            patch.dict(
                "os.environ",
                {
                    "ALLOYDB_HOST": "fake-host",
                    "ALLOYDB_PASSWORD": "test",
                    "USE_ALLOYDB": "false",  # would normally return SAMPLE_RULES
                    "EMBEDDING_BACKEND": "vertex_ai",
                },
            ),
        ):
            result = await get_local_and_traffic_rules(query="anything", tool_context=mock_ctx)

        assert result["status"] == "success"
        assert result["rules"] == [{"city": "Las Vegas", "text": "Real DB rule, not sample."}]
        assert "Sample" not in result.get("note", ""), "Should not be in sample mode when vertex_ai is configured"
