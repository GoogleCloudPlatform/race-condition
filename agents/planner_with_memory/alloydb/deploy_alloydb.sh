#!/usr/bin/env bash
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

# deploy_alloydb.sh — Seed planner_with_memory data into AlloyDB.
#
# What this script does:
#   1. Resolves ALLOYDB_HOST (from env or gcloud).
#   2. Applies schema.sql (idempotent — IF NOT EXISTS / ON CONFLICT).
#   3. Seeds the rules table from seed_rules.sql.
#   4. Seeds the planned_routes table from memory/seeds/*.json via seed_routes.py.
#
# Prerequisites (infra must already be provisioned via terraform apply):
#   Run `terraform apply` in code-infra/projects/dev first.
#
# Usage:
#   cd /Users/lucias/backend
#   bash agents/planner_with_memory/alloydb/deploy_alloydb.sh
#
# Prerequisites:
#   - gcloud authenticated with access to the dev project
#   - psql installed  (brew install libpq && brew link --force libpq)
#   - uv installed
#   - ALLOYDB_PASSWORD env var set (or stored in Secret Manager as am-db-password)

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"   # /Users/lucias/backend
CODE_INFRA_DIR="$(cd "$BACKEND_DIR/../code-infra/projects/dev" && pwd)"

ALLOYDB_USER="${ALLOYDB_USER:-postgres}"
ALLOYDB_DATABASE="${ALLOYDB_DATABASE:-postgres}"
ALLOYDB_PORT="${ALLOYDB_PORT:-5432}"



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "► $*"; }
ok()   { echo "✓ $*"; }
warn() { echo "⚠ $*"; }
die()  { echo "✗ $*" >&2; exit 1; }

require() {
  command -v "$1" &>/dev/null || die "'$1' is required but not installed. $2"
}

require psql   "Install with: brew install libpq && brew link --force libpq"
require gcloud "Install from: https://cloud.google.com/sdk/docs/install"
require uv     "Install from: https://docs.astral.sh/uv/getting-started/installation/"

# ---------------------------------------------------------------------------
# Step 1: Resolve ALLOYDB_PASSWORD
# ---------------------------------------------------------------------------
log "Resolving AlloyDB password..."
if [[ -z "${ALLOYDB_PASSWORD:-}" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
  if SECRET=$(gcloud secrets versions access latest --secret="am-db-password" --project="$PROJECT_ID" 2>/dev/null); then
    export ALLOYDB_PASSWORD="$SECRET"
    ok "Password fetched from Secret Manager (alloydb-password)"
  else
    warn "ALLOYDB_PASSWORD not set and Secret Manager fetch failed."
    warn "Falling back to Terraform hardcoded dev password."
    export ALLOYDB_PASSWORD="DevPassword123!"
  fi
else
  ok "ALLOYDB_PASSWORD already set."
fi
export PGPASSWORD="$ALLOYDB_PASSWORD"

# ---------------------------------------------------------------------------
# Step 2: Resolve ALLOYDB_HOST
# ---------------------------------------------------------------------------
log "Resolving AlloyDB host IP..."
if [[ -z "${ALLOYDB_HOST:-}" ]]; then
  PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
  REGION="${REGION:-us-central1}"

  # Try terraform output first
  if command -v terraform &>/dev/null && [[ -d "$CODE_INFRA_DIR" ]]; then
    ALLOYDB_HOST="$(terraform -chdir="$CODE_INFRA_DIR" output -raw alloydb_ip_address 2>/dev/null || true)"
  fi

  if [[ -z "$ALLOYDB_HOST" ]]; then
    warn "Could not get IP from terraform output — trying gcloud..."
    ALLOYDB_HOST="$(
      gcloud alloydb instances describe agent-memory \
        --cluster=am-cluster \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="value(ipAddress)" 2>/dev/null
    )"
  fi

  [[ -z "$ALLOYDB_HOST" ]] && die "Could not determine ALLOYDB_HOST. Set it manually: export ALLOYDB_HOST=<ip>"
  export ALLOYDB_HOST
  ok "AlloyDB host: $ALLOYDB_HOST"
else
  ok "ALLOYDB_HOST already set: $ALLOYDB_HOST"
fi

# ---------------------------------------------------------------------------
# Validate connectivity
# ---------------------------------------------------------------------------
log "Testing database connectivity..."
psql "host=$ALLOYDB_HOST port=$ALLOYDB_PORT user=$ALLOYDB_USER dbname=$ALLOYDB_DATABASE" \
  --command="SELECT 1;" \
  --quiet \
  || die "Cannot connect to AlloyDB at $ALLOYDB_HOST. Check VPC/IP/password."
ok "Connection successful."

# ---------------------------------------------------------------------------
# Step 4: Apply schema (idempotent)
# ---------------------------------------------------------------------------
log "Applying schema (rules + planned_routes + simulation_records)..."
psql "host=$ALLOYDB_HOST port=$ALLOYDB_PORT user=$ALLOYDB_USER dbname=$ALLOYDB_DATABASE" \
  --file="$SCRIPT_DIR/schema.sql" \
  --quiet
ok "Schema applied."

# ---------------------------------------------------------------------------
# Step 5: Seed rules
# ---------------------------------------------------------------------------
log "Seeding rules table..."
psql "host=$ALLOYDB_HOST port=$ALLOYDB_PORT user=$ALLOYDB_USER dbname=$ALLOYDB_DATABASE" \
  --file="$SCRIPT_DIR/seed_rules.sql" \
  --quiet
RULES_COUNT="$(
  psql "host=$ALLOYDB_HOST port=$ALLOYDB_PORT user=$ALLOYDB_USER dbname=$ALLOYDB_DATABASE" \
    --tuples-only --command="SELECT COUNT(*) FROM rules;" | xargs
)"
ok "Rules table has $RULES_COUNT row(s)."

# ---------------------------------------------------------------------------
# Step 6: Seed planned routes via Python
# ---------------------------------------------------------------------------
log "Seeding planned_routes from memory/seeds/*.json..."
ALLOYDB_HOST="$ALLOYDB_HOST" \
ALLOYDB_PASSWORD="$ALLOYDB_PASSWORD" \
ALLOYDB_DATABASE="$ALLOYDB_DATABASE" \
ALLOYDB_USER="$ALLOYDB_USER" \
  uv run --directory="$BACKEND_DIR" \
    python -m agents.planner_with_memory.alloydb.seed_routes

ROUTE_COUNT="$(
  psql "host=$ALLOYDB_HOST port=$ALLOYDB_PORT user=$ALLOYDB_USER dbname=$ALLOYDB_DATABASE" \
    --tuples-only --command="SELECT COUNT(*) FROM planned_routes;" | xargs
)"
ok "planned_routes table has $ROUTE_COUNT row(s)."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║             AlloyDB Deployment Complete 🦄                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Host:        $ALLOYDB_HOST"
echo "  Database:    $ALLOYDB_DATABASE"
echo "  Rules:       $RULES_COUNT chunk(s)"
echo "  Routes:      $ROUTE_COUNT seed route(s)"
echo ""
echo "Next steps:"
echo "  export ALLOYDB_HOST=$ALLOYDB_HOST"
echo "  export ALLOYDB_PASSWORD=<password>"
echo "  uv run restart   # to restart the planner_with_memory agent"
