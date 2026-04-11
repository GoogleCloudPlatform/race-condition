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

-- AlloyDB full setup for planner_with_memory agent.
-- Run this script once after provisioning the AlloyDB instance.
-- It creates all required tables and configures the embedding auto-refresh.

CREATE EXTENSION IF NOT EXISTS google_ml_integration;
CREATE EXTENSION IF NOT EXISTS vector;



-- ============================================================
-- 1. RULES TABLE  (RAG / vector similarity search)
-- ============================================================

CREATE TABLE IF NOT EXISTS rules (
    source_file VARCHAR(255),
    chunk_id    INT,
    city        VARCHAR(100),
    text        TEXT,
    embedding   VECTOR(3072)
);

-- Auto-refresh embeddings whenever rows are inserted/updated.
CALL ai.initialize_embeddings(
    model_id               => 'gemini-embedding-001',
    table_name             => 'rules',
    content_column         => 'text',
    embedding_column       => 'embedding',
    batch_size             => 50,
    incremental_refresh_mode => 'transactional'
);

-- ============================================================
-- 2. PLANNED ROUTES TABLE  (structured route persistence)
-- ============================================================

CREATE TABLE IF NOT EXISTS planned_routes (
    route_id   VARCHAR(64)  PRIMARY KEY,
    route_data JSONB        NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    eval_score FLOAT,
    eval_result JSONB
);

-- ============================================================
-- 3. SIMULATION RECORDS TABLE
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
-- 4. SIMULATION SUMMARIES TABLE  (RAG / semantic recall)
-- ============================================================
-- Stores a combined prompt + result summary for each simulation run.
-- The embedding column enables vector similarity search to surface
-- the most relevant past simulations when a new prompt arrives.

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

-- Auto-refresh embeddings whenever rows are inserted/updated.
CALL ai.initialize_embeddings(
    model_id               => 'gemini-embedding-001',
    table_name             => 'simulation_summaries',
    content_column         => 'summary',
    embedding_column       => 'embedding',
    batch_size             => 50,
    incremental_refresh_mode => 'transactional'
);
