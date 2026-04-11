---
name: deploying
description: >
  Guides deployment of Race Condition to a GCP project. Use when deploying to
  the cloud, setting up infrastructure with Terraform, or troubleshooting a
  deployment. This is for cloud deployment -- for local development, use the
  getting-started skill instead.
---

# Deploying Race Condition

This skill walks through deploying Race Condition to a GCP project. It covers
infrastructure provisioning with Terraform, application deployment to Cloud Run
and Agent Engine, and post-deploy verification. Each phase has a hard gate --
do not proceed to the next phase until the current one succeeds.

For local development setup, use the `getting-started` skill instead.

## Phase 1: Prerequisites Check

HARD GATE: Do not proceed until all prerequisites are confirmed.

### Required Tools

| Tool | Min version | Check command | Install |
|---|---|---|---|
| Google Cloud SDK | latest | `gcloud --version` | https://cloud.google.com/sdk/docs/install |
| Terraform | 1.5+ | `terraform --version` | https://developer.hashicorp.com/terraform/install |
| Docker | latest | `docker --version` | https://docs.docker.com/get-docker/ |
| uv | latest | `uv --version` | https://docs.astral.sh/uv/ |

### GCP Authentication

Run these commands and verify the output:

```bash
gcloud auth list
```

Must show an active account. If not:

```bash
gcloud auth login --update-adc
```

Then set up Application Default Credentials:

```bash
gcloud auth application-default login
```

### GCP Project

Ask the developer for their GCP project ID. Verify:

```bash
gcloud projects describe PROJECT_ID
```

Requirements:
- Billing must be enabled on the project
- The authenticated user must have Owner or Editor role

Set the project:

```bash
gcloud config set project PROJECT_ID
```

## Phase 2: Feature Selection

Ask the developer which optional features they want to enable. Explain the
cost and capability tradeoffs for each.

| Feature | Extra cost | What it enables |
|---|---|---|
| AlloyDB | ~$200/mo | Route memory with vector embeddings (replaces Cloud SQL) |
| GKE runner cluster | ~$300/mo | GPU-powered runner agents on Kubernetes |
| Maps API key | Per-request pricing | Real map data for route planning (Maps, Places, Weather) |
| Monitoring alerts | Free (alerting only) | Email alerts for Redis memory, NAT egress, etc. |

**Base infrastructure cost:** ~$91/month (Redis, Cloud SQL, Cloud NAT). Compute scales to zero when idle. Each simulation costs ~$3-4 in Gemini API calls.

Generate `infra/terraform.tfvars` from the developer's answers:

```hcl
project_id          = "your-project-id"
db_initial_password = "change-me-to-a-secure-password"
region              = "us-central1"

# Optional features
enable_alloydb      = false
enable_gke          = false
enable_maps_api_key = false
enable_monitoring   = false

# Developer access (optional)
developers = [
  "user:developer@example.com",
]
```

Replace `your-project-id` with the actual project ID. Remind the developer to
set a strong `db_initial_password` and not commit this file (it should be
gitignored).

HARD GATE: `infra/terraform.tfvars` must exist with the correct project ID
before proceeding.

## Phase 3: Infrastructure Provisioning

Run these steps in order. Each step must succeed before the next.

### Step 1: Initialize Terraform

```bash
make infra-init
```

This downloads providers and initializes the Terraform backend.

### Step 2: Review the plan

```bash
make infra-plan
```

Show the plan output to the developer. Confirm they want to proceed. The plan
will list all GCP resources to be created (Cloud Run, Redis, VPC, NAT, etc.).

HARD GATE: Get explicit confirmation from the developer before applying.

### Step 3: Apply infrastructure

```bash
make infra-apply
```

This takes 5-15 minutes depending on which features are enabled. AlloyDB and
GKE each add 5-10 minutes.

### Step 4: Verify outputs

```bash
make infra-output
```

Confirm the outputs show all expected resources. Key outputs to verify:
- Artifact Registry repository URL
- Redis instance connection
- Cloud SQL or AlloyDB connection (depending on selection)
- VPC connector name

### Step 5: Configure Docker for Artifact Registry

```bash
gcloud auth configure-docker REGION-docker.pkg.dev
```

Replace `REGION` with the deployment region (default: `us-central1`).

## Phase 4: Application Deployment

Race Condition deploys end-to-end via a single Cloud Build job
(`cloudbuild-bootstrap.yaml`). The job builds container images in parallel,
pushes them to Artifact Registry, deploys Cloud Run services and IAM via
Terraform (with the just-built image tags), and deploys Agent Engine agents
in parallel. Takes 20-30 minutes.

Two equivalent entry points:

```bash
# Interactive (recommended for first-time deploys; same UX as the Cloud
# Shell button: cost confirmation, project picker, region picker).
bash scripts/deploy.sh

# Non-interactive (for repeat deploys / scripted use).
make deploy PROJECT_ID=PROJECT_ID REGION=us-central1
```

Both entry points end with `gcloud builds submit --config
cloudbuild-bootstrap.yaml ...`. Monitor a running build:

```bash
gcloud builds log --stream BUILD_ID
```

The build ID is printed at the start of the deploy.

HARD GATE: Deployment must complete without errors before proceeding.

## Phase 5: Post-Deploy Verification

### 1. Check Cloud Run services

```bash
gcloud run services list --project=PROJECT_ID --region=REGION
```

All services should show status "Ready". Expected services (names use dashes in Cloud Run):
- `gateway`
- `admin`
- `tester`
- `frontend`
- `dash`
- `runner-autopilot`
- `runner-cloudrun`

### 2. Access the frontend

Open the URL from the `frontend` service. It should load the 3D simulation
environment.

### 3. Access the admin dashboard

Open the URL from the `admin-dash` service. It should show service health
status.

### 4. Verify Agent Engine agents

```bash
gcloud ai agent-engines list --project=PROJECT_ID --region=REGION
```

Expected agents (varies by configuration):
- `planner`
- `simulator`
- `runner` (or `runner-autopilot`)

HARD GATE: All services must be running and accessible before proceeding to
optional post-deploy steps.

## Phase 6: Optional Post-Deploy Steps

Only run the sections below that match the features the developer enabled in
Phase 2.

### Maps API Key (if enabled)

The Terraform apply created an API key stored in Secret Manager. It needs
manual restriction in the Cloud Console:

1. Go to **APIs & Services > Credentials** in the Cloud Console
2. Find the key named `maps-places-weather-key`
3. Under **API restrictions**, select **Restrict key** and add:
   - Maps JavaScript API
   - Places API (New)
   - Weather API
4. Save. The key value is already stored in Secret Manager and referenced by
   the planner agent.

### AlloyDB (if enabled)

Seed the database with schema and initial route data:

```bash
bash agents/planner_with_memory/alloydb/deploy_alloydb.sh
```

This creates tables, installs the pgvector extension, and loads seed routes.
Verify with the admin dashboard -- the planner-with-memory agent should show as
connected.

### GKE Runner (if enabled)

When `enable_gke = true` in `infra/terraform.tfvars`, the GKE cluster and the
runner-on-GKE workload are provisioned by Terraform during `make infra-apply`
(modules `gke-model-serving` and `gke-runner`). There is no separate deploy
step for the runner image -- it ships with the cluster.

After the cluster is up:

1. Get the runner's Internal Load Balancer IP from `make infra-output`
   (or `kubectl get svc -n runner runner-gke`).
2. Set `RUNNER_GKE_INTERNAL_URL=http://<ILB_IP>` in the gateway Cloud Run
   service environment via the Cloud Console or
   `gcloud run services update gateway --update-env-vars=...`.

### Monitoring (if enabled)

Terraform creates alert policies but does not configure notification channels:

1. Go to **Monitoring > Alerting** in the Cloud Console
2. Create a notification channel (email, Slack, PagerDuty, etc.)
3. Edit each alert policy to add the notification channel

Alert policies cover Redis memory usage, NAT gateway egress, and Cloud Run
error rates.

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Permission denied" on any step | Missing Owner/Editor role | Grant the role in IAM, or ask a project admin |
| "API not enabled" errors | Terraform should enable APIs, but propagation can lag | `gcloud services enable API_NAME --project=PROJECT_ID` |
| "Quota exceeded" | Default quotas too low for the deployment | Request increases at Cloud Console > IAM & Admin > Quotas |
| "VPC connector not found" during deploy | Infrastructure not fully provisioned | Wait for `make infra-apply` to finish, then retry |
| Agent Engine deploy fails | Wrong location configured | Verify `GOOGLE_CLOUD_LOCATION` is set to the region (e.g., `us-central1`), not `global` |
| Cloud Build timeout | Large images or slow network | Retry the same `make deploy` / `bash scripts/deploy.sh` invocation -- `cloudbuild-bootstrap.yaml` is idempotent |
| "Already exists" on re-deploy | Previous partial deploy left resources | Run `make deploy` again -- it is idempotent |

## Teardown

To remove all deployed resources:

### Step 1: Destroy Terraform-managed infrastructure

```bash
make infra-destroy
```

Review the plan and confirm. This removes all GCP resources created by
Terraform (VPC, Redis, Cloud SQL/AlloyDB, NAT, etc.).

### Step 2: Clean up non-Terraform resources

If any resources were created outside Terraform (manual Cloud Run deploys,
extra Agent Engine agents), delete them separately:

```bash
# List and delete Cloud Run services
gcloud run services list --project=PROJECT_ID --region=REGION
gcloud run services delete SERVICE_NAME --project=PROJECT_ID --region=REGION

# List and delete Agent Engine agents
gcloud ai agent-engines list --project=PROJECT_ID --region=REGION
gcloud ai agent-engines delete AGENT_ID --project=PROJECT_ID --region=REGION
```

### Step 3: Verify cleanup

```bash
gcloud run services list --project=PROJECT_ID --region=REGION
gcloud ai agent-engines list --project=PROJECT_ID --region=REGION
```

Both commands should return empty results.
