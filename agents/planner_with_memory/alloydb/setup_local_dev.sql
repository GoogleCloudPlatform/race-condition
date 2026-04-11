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

SET search_path = local_dev, public;

CREATE TABLE IF NOT EXISTS local_dev.regulations (
    source_file VARCHAR(255),
    chunk_id INT,
    city VARCHAR(100),
    text TEXT,
    embedding VECTOR(3072)
);

CALL ai.initialize_embeddings(
    model_id => 'gemini-embedding-001',
    table_name => 'local_dev.regulations',
    content_column => 'text',
    embedding_column => 'embedding',
    batch_size => 50,
    incremental_refresh_mode => 'transactional'
);
