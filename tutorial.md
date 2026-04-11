# Race Condition -- one-click deploy

This tutorial deploys Race Condition to your own GCP project. It takes
about 15 minutes and runs entirely inside this Cloud Shell session, so
you don't need to install anything locally.

Cost runs about $2-5 per day with the default scale-to-zero sizing. You
can tear it down whenever (`terraform destroy`, instructions at the
bottom). The [README cost note](README.md#cost-note) has the full
breakdown if you want to know where the money goes.

## Step 1: run the deploy script

```bash
./scripts/deploy.sh
```

What the script does, in order:

1. Shows you the cost summary and asks for confirmation.
2. Prompts for a GCP project ID. You can type one in or pick from
   your accessible projects.
3. Prompts for a region. The list is curated to regions where Cloud
   Run, Memorystore, Cloud SQL, and Vertex AI all coexist (which is
   fewer than you'd think).
4. Pre-flights your project. This enables the bootstrap APIs
   (`cloudbuild`, `compute`, `iam`, `run`, etc.) and grants the
   Cloud Build default service account the IAM roles to run
   Terraform apply. `roles/owner` alone is not enough — yes,
   really. The pre-flight is safe to re-run after a partial deploy.
5. Submits a single Cloud Build job that handles everything else.

## Step 2: wait for the build

The Cloud Build orchestrator (`cloudbuild-bootstrap.yaml`) runs in
four phases. Total wall time is around 15 minutes.

Phase A takes 4-5 minutes. Terraform provisions the base infra (VPC,
IAM, Memorystore, Cloud SQL, Pub/Sub topics, Artifact Registry).
Then dedicated Cloud Build steps run schema migration, rule seeding,
and a Vertex AI embedding backfill against the fresh Cloud SQL
instance.

Phase B takes about 7 minutes and is the most parallel part: seven
Docker image builds and five Vertex AI Agent Engine deploys all run
side by side. This is where the wait usually feels longest.

Phase C is another ~3 minutes. Terraform deploys the Cloud Run
services and IAM bindings, wiring the freshly-built image tags and
AGENT_URLS into env vars.

Phase D is the easy one — about 30 seconds — and just prints the
user-facing URLs.

You can follow progress in the Cloud Build console. The script
prints the URL right after it submits.

## Step 3: open the frontend

When the build finishes, the last step prints the frontend URL.
Open it, then click "Run Simulation" to launch your first race.

## Tear down

When you're done:

```bash
cd infra && terraform destroy
```

This removes the GCP resources the deploy created. The Cloud Storage
bucket holding Terraform state stays put, so the next deploy picks
up cleanly.
