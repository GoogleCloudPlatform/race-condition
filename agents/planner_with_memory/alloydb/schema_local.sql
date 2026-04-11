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

-- Local development schema for planner_with_memory agent.
-- Used by the local Postgres container (docker-compose.yml postgres service).
--
-- Differences from schema.sql (AlloyDB production):
--   - Skips CREATE EXTENSION google_ml_integration (AlloyDB-only)
--   - Skips CALL ai.initialize_embeddings(...) (AlloyDB-only)
--   - Uses standard pgvector extension for the embedding VECTOR column
--
-- The get_local_and_traffic_rules tool will fail gracefully locally
-- (returns {"status": "error", "message": "..."}) since ai.embedding()
-- is not available. All route persistence tools work identically.

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. RULES TABLE  (vector column present; search disabled locally)
-- ============================================================

CREATE TABLE IF NOT EXISTS rules (
    source_file VARCHAR(255),
    chunk_id    INT,
    city        VARCHAR(100),
    text        TEXT,
    embedding   VECTOR(3072)
);

-- ============================================================
-- 2. PLANNED ROUTES TABLE  (full fidelity locally)
-- ============================================================

CREATE TABLE IF NOT EXISTS planned_routes (
    route_id    VARCHAR(64)  PRIMARY KEY,
    route_data  JSONB        NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    eval_score  FLOAT,
    eval_result JSONB
);

-- ============================================================
-- 3. SIMULATION RECORDS TABLE  (full fidelity locally)
-- ============================================================

CREATE TABLE IF NOT EXISTS simulation_records (
    simulation_id VARCHAR(64)  PRIMARY KEY,
    route_id      VARCHAR(64)  NOT NULL REFERENCES planned_routes(route_id) ON DELETE CASCADE,
    sim_result    JSONB        NOT NULL,
    simulated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- FK lookup index: get_route joins simulation_records by route_id.
-- This table grows with every simulation run — without an index,
-- the join degrades to a sequential scan as rows accumulate.
CREATE INDEX IF NOT EXISTS idx_simulation_records_route_id
    ON simulation_records (route_id);

-- ============================================================
-- 4. SIMULATION SUMMARIES TABLE  (vector column present; search requires client-side embedding)
-- ============================================================
-- Stores a combined prompt + result summary for each simulation run.
-- The embedding column enables vector similarity search to surface
-- the most relevant past simulations when a new prompt arrives.
-- Locally, embeddings are generated client-side via the google-genai SDK
-- (Vertex AI) rather than via AlloyDB's ai.initialize_embeddings().

CREATE TABLE IF NOT EXISTS simulation_summaries (
    summary_id  VARCHAR(64)  PRIMARY KEY,
    city        VARCHAR(100),
    prompt      TEXT         NOT NULL,
    summary     TEXT         NOT NULL,
    route_id    VARCHAR(64),
    sim_result  JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    embedding   VECTOR(3072)
);
