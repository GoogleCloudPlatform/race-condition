---
name: getting-started
description: >
  Guides setup of the Race Condition project from clone to running simulation.
  Use when the developer wants to get the project running locally, install
  dependencies, configure GCP credentials, or troubleshoot startup issues.
---

# Getting Started with Race Condition

This skill walks through setting up Race Condition for local development. Some
steps are fully automatable (installing dependencies, building code). Others
require the developer to act in a browser or terminal (GCP auth, API key
creation). Each step is marked AUTO or MANUAL.

## Prerequisites Check

Run `make check-prereqs` to verify required tools. If any are missing, tell
the developer what to install before continuing.

| Tool | Min version | Install |
|---|---|---|
| Go | 1.25+ | https://go.dev/dl/ |
| Python | 3.13+ | Installed by uv |
| uv | latest | https://docs.astral.sh/uv/ |
| Node.js | 24+ | https://nodejs.org/ |
| Docker + Compose | latest | https://docs.docker.com/get-docker/ |
| Google Cloud SDK | latest | https://cloud.google.com/sdk/docs/install |

## Setup Workflow

### Step 1: Clone the repo (AUTO)

```bash
git clone https://github.com/GoogleCloudPlatform/race-condition.git
cd race-condition
```

Skip if the developer already has the repo.

### Step 2: GCP authentication (MANUAL)

These commands are interactive (browser OAuth). Tell the developer to run them:

```bash
gcloud auth login --update-adc
gcloud config set project PROJECT_ID
```

Ask for their GCP project ID. They need a project with billing enabled and
Owner access (or `roles/aiplatform.user` at minimum).

### Step 3: Enable required APIs (AUTO)

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  generativelanguage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  pubsub.googleapis.com \
  iam.googleapis.com

gcloud auth application-default set-quota-project PROJECT_ID
```

API enablement takes 1-2 minutes to propagate. If 403 errors appear on first
start, wait a minute and run `make restart`.

### Step 4: Initialize the project (AUTO)

```bash
make init
```

This checks prerequisites, creates `.env` from `.env.example`, installs Python
deps (`uv sync`), installs and builds web frontends, starts Docker
infrastructure (Redis, Pub/Sub emulator, PostgreSQL), and builds Go services.

### Step 5: Configure .env (AUTO)

Replace the placeholder project ID:

```bash
# macOS
sed -i '' 's/your-gcp-project-id/ACTUAL_PROJECT_ID/g' .env

# Linux
sed -i 's/your-gcp-project-id/ACTUAL_PROJECT_ID/g' .env
```

Detect the OS and use the correct `sed` variant.

### Step 6: Start the simulation (AUTO)

```bash
make start
```

Once started:
- **Frontend (3D)**: http://localhost:9119
- **Admin dashboard**: http://localhost:9100
- **Tester UI**: http://localhost:9112

### Step 7: Google Maps API key (MANUAL, optional)

The Planner works without a Maps key but produces better routes with one.

1. Enable APIs:
   ```bash
   gcloud services enable apikeys.googleapis.com \
     agentregistry.googleapis.com cloudapiregistry.googleapis.com \
     mapstools.googleapis.com places.googleapis.com weather.googleapis.com
   ```

2. Create a key at https://console.cloud.google.com/apis/credentials.
   Restrict to: Cloud API Registry API, Maps Grounding Lite API, Places API
   (New), Weather API.

3. Add to `.env`: `GOOGLE_MAPS_API_KEY=AIza...`

4. Run `make restart`.

## Troubleshooting

| Problem | Fix |
|---|---|
| Port conflicts | `make stop` first, then `lsof -i :PORT` to find conflicts |
| Docker not running | Start Docker Desktop, retry |
| 403 errors on first start | API enablement propagation; wait 1-2 min, `make restart` |
| Python import errors | Run `uv sync` to reinstall dependencies |
| High API costs | Use `runner_autopilot` (deterministic, zero LLM calls) or set `RUNNER_MODEL=ollama_chat/gemma4:e2b` in `.env` for free local inference |

## Next Steps

- Run tests with `make test`
- To modify an agent, edit files in `agents/` and run `make restart`
- To understand the architecture, use the `exploring-the-codebase` skill
- To set up a contributor workflow, use the `contributing` skill
