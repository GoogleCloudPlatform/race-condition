---
name: deploying
description: >
  Guides deployment of Race Condition to a GCP project. Use when deploying to
  the cloud, setting up infrastructure with Terraform, or troubleshooting a
  deployment. This is for cloud deployment -- for local development, use the
  getting-started skill instead.
---

# Deploying Race Condition

This skill walks through a cloud deploy of Race Condition to a GCP project:
Terraform for the infra, Cloud Run and Agent Engine for the app, then a
verification pass once it's up. The phases are gated. If a phase fails, stop
and fix it. Don't try to push past it.

For local dev setup, use the `getting-started` skill instead.

## Phase 1: prerequisites check

HARD GATE: Do not proceed until all prerequisites are confirmed.

### Required tools

| Tool | Min version | Check command | Install |
|---|---|---|---|
| Google Cloud SDK | latest | `gcloud --version` | https://cloud.google.com/sdk/docs/install |
| Terraform | 1.5+ | `terraform --version` | https://developer.hashicorp.com/terraform/install |
| Docker | latest | `docker --version` | https://docs.docker.com/get-docker/ |
| uv | latest | `uv --version` | https://docs.astral.sh/uv/ |

### GCP authentication

Check who you're logged in as:

```bash
gcloud auth list
```

There should be an active account. If not:

```bash
gcloud auth login --update-adc
```

Then set up Application Default Credentials separately (yes, this is a
second login; gcloud and ADC use different token stores):

```bash
gcloud auth application-default login
```

### GCP project

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

## Phase 2: feature selection

Ask the developer which optional features they want on. Each one costs
something, so explain the tradeoff before enabling it.

| Feature | Extra cost | What it enables |
|---|---|---|
| AlloyDB | ~$200/mo | Route memory with vector embeddings (replaces Cloud SQL) |
| GKE runner cluster | ~$300/mo | GPU-powered runner agents on Kubernetes |
| Cloud Run runner | ~$0 idle, scales with load | LLM-powered runner agents on Cloud Run (alternative to GKE) |
| Maps API key | Per-request pricing | Real map data for route planning (Maps, Places, Weather) |
| Monitoring alerts | Free (alerting only) | Email alerts for Redis memory, NAT egress, etc. |

Base infrastructure runs about $91/month (Redis, Cloud SQL, Cloud NAT).
Compute scales to zero when idle, so the rest is usage-based. Each
simulation costs around $3-4 in Gemini API calls.

Generate `infra/terraform.tfvars` from the developer's answers:

```hcl
project_id          = "your-project-id"
db_initial_password = "change-me-to-a-secure-password"
region              = "us-central1"

# Optional features
enable_alloydb         = false
enable_gke             = false
enable_runner_cloudrun = false
enable_maps_api_key    = false
enable_monitoring      = false
alert_email            = ""  # required only when enable_monitoring = true

# Developer access (optional)
developers = [
  "user:developer@example.com",
]
```

Swap in the real project ID. Remind the developer to pick a strong
`db_initial_password` and not commit the file; it should be gitignored.

HARD GATE: `infra/terraform.tfvars` must exist with the correct project ID
before proceeding.

## Phase 3: infrastructure provisioning

Run these in order. Each step must succeed before the next.

### Step 1: initialize Terraform

```bash
make infra-init
```

This downloads providers and initializes the Terraform backend.

### Step 2: review the plan

```bash
make infra-plan
```

Show the plan output to the developer. The plan lists every GCP resource
that will be created (Cloud Run, Redis, VPC, NAT, etc.).

HARD GATE: Explicit confirmation from the developer before applying.

### Step 3: apply infrastructure

```bash
make infra-apply
```

This takes 5-15 minutes depending on which features are on. AlloyDB and
GKE each add another 5-10 minutes on top.

### Step 4: verify outputs

```bash
make infra-output
```

Check the outputs include the things you'll need downstream:
- Artifact Registry repository URL
- Redis instance connection
- Cloud SQL or AlloyDB connection (whichever you picked)
- VPC connector name

### Step 5: configure Docker for Artifact Registry

```bash
gcloud auth configure-docker REGION-docker.pkg.dev
```

Swap `REGION` for your deployment region (default: `us-central1`).

## Phase 4: application deployment

The whole app deploys via one Cloud Build job (`cloudbuild-bootstrap.yaml`).
It builds container images in parallel, pushes them to Artifact Registry,
runs Terraform to deploy the Cloud Run services and IAM with those image
tags, and deploys the Agent Engine agents in parallel. Plan for 20-30
minutes start to finish.

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

The build ID prints at the start of the deploy.

HARD GATE: Deployment must complete without errors before proceeding.

## Phase 5: post-deploy verification

### 1. Check Cloud Run services

```bash
gcloud run services list --project=PROJECT_ID --region=REGION
```

Every service should be "Ready". Cloud Run names use dashes:
- `gateway`
- `admin`
- `tester`
- `frontend`
- `dash`
- `runner-autopilot`
- `runner-cloudrun`

### 2. Open the frontend

Grab the URL from the `frontend` service and open it. The 3D simulation
should load.

### 3. Open the admin dashboard

The `admin-dash` service URL gets you the service health view.

### 4. Verify Agent Engine agents

There is no `gcloud` subcommand for Agent Engines. List them via the
Vertex AI REST API:

```bash
TOKEN=$(gcloud auth application-default print-access-token)
BASE="https://aiplatform.googleapis.com"  # us-central1; for other regions use https://${REGION}-aiplatform.googleapis.com
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE/v1beta1/projects/PROJECT_ID/locations/REGION/reasoningEngines" \
  | python3 -c 'import json,sys; [print(e["displayName"]) for e in json.load(sys.stdin).get("reasoningEngines", [])]'
```

You'll see something like (the exact list depends on what's enabled):
- `planner`
- `simulator`
- `planner_with_eval`
- `planner_with_memory`
- `simulator_with_failure`

HARD GATE: All services must be running and accessible before moving on to
the optional steps.

## Phase 6: optional post-deploy steps

Only the sections that match features enabled in Phase 2 apply here. Skip
the rest.

### Maps API key (if enabled)

Terraform created the key and stored it in Secret Manager, but the API
restrictions still have to be applied by hand in the Cloud Console:

1. Go to **APIs & Services > Credentials** in the Cloud Console
2. Find the key named `maps-places-weather-key`
3. Under **API restrictions**, select **Restrict key** and add:
   - Maps JavaScript API
   - Places API (New)
   - Weather API
4. Save. The key value is already in Secret Manager and the planner agent
   reads it from there.

### AlloyDB (if enabled)

Seed the database with the schema and initial route data:

```bash
bash agents/planner_with_memory/alloydb/deploy_alloydb.sh
```

This creates the tables, installs pgvector, and loads the seed routes.
Check the admin dashboard once it finishes; the planner-with-memory
agent should show as connected.

### GKE runner (if enabled)

When `enable_gke = true` in `infra/terraform.tfvars`, the GKE cluster and
the runner-on-GKE workload are both provisioned by Terraform during
`make infra-apply` (via the `gke-model-serving` and `gke-runner` modules).
There's no separate deploy step for the runner image; it ships with the
cluster.

Once the cluster is up:

1. Get the runner's Internal Load Balancer IP from `make infra-output`
   (or `kubectl get svc -n runner runner-gke`).
2. Set `RUNNER_GKE_INTERNAL_URL=http://<ILB_IP>` on the gateway Cloud Run
   service. Either do it in the Cloud Console or run
   `gcloud run services update gateway --update-env-vars=...`.

### Monitoring (if enabled)

Terraform creates the alert policies but doesn't wire up any notification
channels. That part is on you:

1. Go to **Monitoring > Alerting** in the Cloud Console.
2. Create a notification channel (email, Slack, PagerDuty, whatever).
3. Edit each alert policy to point at it.

The policies cover Redis memory usage, NAT gateway egress, and Cloud Run
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

The one-command path:

```bash
./scripts/teardown.sh
```

It mirrors `scripts/deploy.sh`'s UX: pick the project, pick the region,
type `destroy` to confirm. The script then:

1. Deletes every Vertex AI Agent Engine in that project + region (REST
   API, since `gcloud` has no AE subcommand).
2. Runs `terraform init -reconfigure` against the GCS state bucket
   (`gs://${PROJECT_ID}-tf-state`, prefix `oss/state`).
3. Runs `terraform destroy -auto-approve` with the same vars
   `deploy.sh` used.
4. Optionally deletes the state bucket itself (asks at the end;
   default keep, so a redeploy stays fast).

Total wall time is around 3-5 minutes.

### Manual fallback

If you need to drive teardown by hand (debugging the script, partial
cleanup, etc.), the same operations broken out:

```bash
# 1. Agent Engines (REST API; no gcloud subcommand exists)
TOKEN=$(gcloud auth application-default print-access-token)
BASE="https://aiplatform.googleapis.com"  # us-central1 host; regional variant for other regions
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE/v1beta1/projects/PROJECT_ID/locations/REGION/reasoningEngines" \
  | python3 -c 'import json,sys; [print(e["name"]) for e in json.load(sys.stdin).get("reasoningEngines", [])]' \
  | while read name; do
      curl -sS -X DELETE -H "Authorization: Bearer $TOKEN" \
        "$BASE/v1beta1/${name}?force=true" >/dev/null
    done

# 2. Terraform-managed infra (NOT `make infra-destroy` -- that target
#    skips `terraform init` and fails from a fresh shell because the
#    GCS backend isn't initialized).
cd infra
terraform init -reconfigure \
  -backend-config="bucket=PROJECT_ID-tf-state" \
  -backend-config="prefix=oss/state"
terraform destroy -auto-approve \
  -var "project_id=PROJECT_ID" \
  -var "region=REGION"

# 3. Optional: state bucket
gcloud storage rm --recursive "gs://PROJECT_ID-tf-state" --project=PROJECT_ID
```

### What teardown does NOT remove

- The GCP project itself — delete it from the Cloud Console if you want
  every trace gone.
- Artifact Registry images — pennies per month at this scale; kept so
  a future redeploy is fast.
- Cloud Build history and logs.
