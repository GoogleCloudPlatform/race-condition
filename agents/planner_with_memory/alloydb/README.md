# AlloyDB Data Assets

This directory contains all AlloyDB SQL schemas and data seeding assets for the `planner_with_memory` agent.

## Directory Structure

```
alloydb/
├── schema.sql            # Full DDL (AlloyDB): regulations, planned_routes, simulation_records, simulation_summaries
├── schema_local.sql      # Local DDL (pgvector): same 4 tables, no AlloyDB-only extensions
├── seed_local.sql        # Local seed data with pre-computed Gemini embeddings (auto-loaded by docker-compose)
├── seed_regulations.sql  # Idempotent INSERT of regulation chunks (AlloyDB production)
├── seed_routes.py        # Python script: seeds planned_routes from memory/seeds/*.json (AlloyDB production)
├── deploy_alloydb.sh     # Full deployment script for AlloyDB environments
├── LEGISLATION.txt       # Raw regulation text (source for RAG chunks)
└── README.md             # This file
```

## Tables (4)

| Table | Purpose | Vector Column |
|---|---|---|
| `regulations` | RAG: local laws and traffic rules | `embedding VECTOR(3072)` |
| `planned_routes` | Route persistence with GeoJSON data | — |
| `simulation_records` | Simulation results (FK to planned_routes) | — |
| `simulation_summaries` | RAG: semantic recall of past simulations | `embedding VECTOR(3072)` |

## Local Development (docker-compose)

Local Postgres is fully automatic. `docker-compose up postgres` (or `uv run start`):

1. Creates all 4 tables via `schema_local.sql` (mounted as `01_schema.sql`)
2. Seeds 3 regulation chunks with pre-computed 3072-dim Gemini embeddings and
   4 marathon route plans via `seed_local.sql` (mounted as `02_seed.sql`)

### Local Vector Search

When `USE_ALLOYDB=false` (default), the memory tools use client-side embedding
generation via the `google-genai` SDK (Vertex AI with ADC):

- `get_local_and_traffic_rules`: Generates a query embedding client-side, then
  runs a standard pgvector cosine distance query against pre-computed seed
  embeddings. Falls back to sample regulations if ADC is unavailable.
- `recall_past_simulations`: Same pattern against `simulation_summaries`.
- `store_simulation_summary`: Persists to local Postgres (embedding column is
  NULL; embeddings are generated at query time).

### Regenerating Seed Data

If regulation text or seed routes change, regenerate `seed_local.sql`:

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
  uv run python scripts/ops/generate_local_seeds.py
```

After regenerating, delete the `alloydb-local-data` Docker volume to
re-initialize:

```bash
docker-compose down -v && docker-compose up postgres
```

## AlloyDB Production Setup (after `terraform apply`)

### 1. Apply the schema

```bash
export PGPASSWORD=$ALLOYDB_PASSWORD
psql "host=$ALLOYDB_HOST user=postgres dbname=postgres" -f alloydb/schema.sql
```

### 2. Seed regulations (RAG data)

```bash
psql "host=$ALLOYDB_HOST user=postgres dbname=postgres" -f alloydb/seed_regulations.sql
```

Embeddings are generated automatically by AlloyDB's `ai.initialize_embeddings` trigger.

### 3. Seed route plans

```bash
ALLOYDB_HOST=... ALLOYDB_PASSWORD=... \
  uv run python -m agents.planner_with_memory.alloydb.seed_routes
```

### Full Deployment

```bash
bash agents/planner_with_memory/alloydb/deploy_alloydb.sh
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `USE_ALLOYDB` | | `false` | `true` for AlloyDB Auth Proxy; `false` for local Postgres |
| `ALLOYDB_HOST` | ✅ | — | Private IP of AlloyDB instance (or `127.0.0.1` locally) |
| `ALLOYDB_PORT` | | `5432` | DB port (`8104` locally via docker-compose) |
| `ALLOYDB_DATABASE` | | `postgres` | Database name |
| `ALLOYDB_USER` | | `postgres` | DB user |
| `ALLOYDB_PASSWORD` | ✅ (prod) | `localdev` | DB password |
| `ALLOYDB_SCHEMA` | | `public` | Schema search path |
| `ALLOYDB_MCP_URL` | ✅ (agent) | — | Managed MCP server URL for SQL tool |

## RAG Query Patterns

### AlloyDB (production)

Uses the `ai.embedding()` SQL function for server-side embedding:

```sql
SELECT text, (embedding <=> ai.embedding('gemini-embedding-001', :query)::vector) AS distance
FROM regulations
WHERE city = :city
ORDER BY distance ASC
LIMIT 5;
```

### Local Postgres (development)

Uses client-side embedding via `google-genai` SDK, then standard pgvector:

```sql
SELECT city, text, (embedding <=> $1::vector) AS distance
FROM regulations
ORDER BY distance ASC
LIMIT $2;
```
