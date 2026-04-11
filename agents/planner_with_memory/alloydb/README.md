# AlloyDB Data Assets

This directory contains all AlloyDB SQL schemas and data seeding assets for the `planner_with_memory` agent.

## Directory Structure

```
alloydb/
├── schema.sql            # Full DDL: regulations, planned_routes, simulation_records
├── LEGISLATION.txt       # Raw regulation text (source for RAG chunks)
├── seed_regulations.sql  # Idempotent INSERT of regulation chunks → regulations table
└── seed_routes.py        # Python script: seeds planned_routes from memory/seeds/*.json
```

## One-Time Setup (after `terraform apply`)

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

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALLOYDB_HOST` | ✅ | — | Private IP of AlloyDB instance |
| `ALLOYDB_DATABASE` | | `postgres` | Database name |
| `ALLOYDB_USER` | | `postgres` | DB user |
| `ALLOYDB_PASSWORD` | ✅ | — | DB password |
| `ALLOYDB_MCP_URL` | ✅ (agent) | — | Managed MCP server URL for SQL tool |

## RAG Query Pattern

The agent queries regulations via the AlloyDB MCP tool (`execute_sql`):

```sql
SELECT text, (embedding <=> embedding('gemini-embedding-001', :query)::vector) AS distance
FROM regulations
WHERE city = :city
ORDER BY distance ASC
LIMIT 5;
```
