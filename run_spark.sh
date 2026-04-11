#!/bin/bash
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

set -euo pipefail

# Required environment variables (set these before running):
#   PROCESSOR_ID    — Document AI processor ID
#   ALLOYDB_PASS    — AlloyDB password (fetch from Secret Manager:
#                     gcloud secrets versions access latest --secret=am-db-password --project=n26-devkey-simulation-dev)
#
# Optional overrides (defaults shown):
#   PROJECT_ID, LOCATION, GCS_FILE_LOCATION, ALLOYDB_IP, ALLOYDB_USER, ALLOYDB_SCHEMA

export LOCAL_DEV=true
export PROJECT_ID="${PROJECT_ID:-n26-devkey-simulation-dev}"
export LOCATION="${LOCATION:-us}"
export GCS_FILE_LOCATION="${GCS_FILE_LOCATION:-gs://n26-xch/laws_and_regulations}"
export ALLOYDB_IP="${ALLOYDB_IP:-127.0.0.1}"
export ALLOYDB_USER="${ALLOYDB_USER:-postgres}"
export ALLOYDB_SCHEMA="${ALLOYDB_SCHEMA:-local_dev}"

if [ -z "${PROCESSOR_ID:-}" ]; then
  echo "Error: PROCESSOR_ID is required. Set it before running this script." >&2
  exit 1
fi

if [ -z "${ALLOYDB_PASS:-}" ]; then
  echo "Error: ALLOYDB_PASS is required. Fetch from Secret Manager:" >&2
  echo "  gcloud secrets versions access latest --secret=am-db-password --project=n26-devkey-simulation-dev" >&2
  exit 1
fi

uv run --with pyspark --with google-cloud-documentai --with google-cloud-storage --with python-dotenv --with "google-cloud-alloydb-connector[pg8000]" --with sqlalchemy python scripts/ops/spark_alloydb_processor.py --city "Las Vegas"
