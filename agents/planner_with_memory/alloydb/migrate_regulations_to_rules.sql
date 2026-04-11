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

-- Migration: rename the `regulations` table to `rules`.
-- This script is IDEMPOTENT — it can be safely run multiple times.
--
-- Uses ALTER TABLE RENAME which is atomic, zero-copy, and preserves
-- all indexes, constraints, triggers, and ai.initialize_embeddings
-- registrations (Postgres updates the catalog entry in-place).
--
-- ┌─────────────────────────────────────────────────────────────────┐
-- │  SCHEMA CONFIGURATION                                           │
-- │  Default: 'public'. To migrate a different schema, edit the     │
-- │  SET line below before running, e.g.:                           │
-- │    SET migrate.schema = 'local_dev';                            │
-- └─────────────────────────────────────────────────────────────────┘
SET migrate.schema = 'public';

DO $$
DECLARE
    v_schema             TEXT    := current_setting('migrate.schema', true);
    v_regulations_exists BOOLEAN;
    v_rules_exists       BOOLEAN;
BEGIN
    -- Default to 'public' if the setting is missing or empty.
    IF v_schema IS NULL OR v_schema = '' THEN
        v_schema := 'public';
    END IF;

    RAISE NOTICE 'Running migration in schema: %', v_schema;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = v_schema
          AND table_name   = 'regulations'
    ) INTO v_regulations_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = v_schema
          AND table_name   = 'rules'
    ) INTO v_rules_exists;

    -- Already migrated: rules exists, regulations does not.
    IF v_rules_exists AND NOT v_regulations_exists THEN
        RAISE NOTICE 'Migration already applied: `%.rules` exists and `regulations` is gone. Skipping.', v_schema;
        RETURN;
    END IF;

    -- Nothing to migrate.
    IF NOT v_regulations_exists AND NOT v_rules_exists THEN
        RAISE NOTICE 'Neither `%.regulations` nor `%.rules` found. Nothing to migrate.', v_schema, v_schema;
        RETURN;
    END IF;

    -- Partial state: both tables exist (from a prior failed copy-based migration).
    -- Drop the copy and rename the original to preserve catalog registrations.
    IF v_regulations_exists AND v_rules_exists THEN
        RAISE NOTICE 'Both tables exist in schema %. Dropping copy `rules` and renaming `regulations`.', v_schema;
        EXECUTE format('DROP TABLE %I.rules', v_schema);
        EXECUTE format('ALTER TABLE %I.regulations RENAME TO rules', v_schema);
        RAISE NOTICE 'Renamed `%.regulations` → `%.rules`. Migration complete.', v_schema, v_schema;
        RETURN;
    END IF;

    -- Normal migration: only regulations exists. Atomic rename.
    RAISE NOTICE 'Renaming `%.regulations` → `%.rules`...', v_schema, v_schema;
    EXECUTE format('ALTER TABLE %I.regulations RENAME TO rules', v_schema);
    RAISE NOTICE 'Done. All indexes, constraints, and embedding registrations preserved.';
END;
$$;
