# Race Condition -- One-Click Deploy

## Welcome

This tutorial walks you through deploying Race Condition to your own
GCP project in about 15 minutes. Everything runs in this Cloud Shell
session -- nothing to install locally.

**Cost:** ~$2-5 per day with the default scale-to-zero sizing. Tear
down anytime with `terraform destroy` (instructions at the end). See
the [README cost note](README.md#cost-note) for the breakdown.

## Step 1: Run the deploy script

Run:

```bash
./scripts/deploy.sh
```

The script will:

1. Show you the cost summary and ask for confirmation.
2. Prompt for the GCP project ID (free-text or pick from your
   accessible projects).
3. Prompt for the region (curated allowlist of regions where
   Cloud Run, Memorystore, Cloud SQL, and Vertex AI all coexist).
4. Pre-flight your project: enable the APIs Cloud Build needs to
   bootstrap (`cloudbuild`, `compute`, `iam`, `run`, etc.) and grant
   the Cloud Build default service account the IAM roles required to
   run Terraform apply (`roles/owner` is not sufficient on its own).
   Idempotent -- safe to re-run after a partial deploy.
5. Submit a single Cloud Build job that does everything else.

## Step 2: Wait for the build

The Cloud Build orchestrator (`cloudbuild-bootstrap.yaml`) runs in
four phases. Total wall time is ~15 minutes:

  * **Phase A (~4-5 min)** -- Terraform provisions the base infra
    (VPC, IAM, Memorystore, Cloud SQL, Pub/Sub topics, Artifact
    Registry), then dedicated Cloud Build steps run schema migration,
    rule seeding, and Vertex AI embedding backfill against the new
    Cloud SQL instance.
  * **Phase B (~7 min, parallel)** -- Seven Docker image builds and
    five Vertex AI Agent Engine deploys run side-by-side.
  * **Phase C (~3 min)** -- Terraform deploys Cloud Run services and
    IAM bindings, wiring image tags and AGENT_URLS into env vars.
  * **Phase D (~30 sec)** -- Final step prints the user-facing URLs.

You can follow progress in the Cloud Build console (the script prints
the URL when it submits).

## Step 3: Open the frontend

When the build finishes, the last step prints the frontend URL.
Click it to open the simulation, then click "Run Simulation" to
launch your first race.

## Tear down

When you're done, destroy everything with:

```bash
cd infra && terraform destroy
```

This removes all GCP resources created by the deploy. The Cloud
Storage bucket holding Terraform state is preserved so a future
re-deploy is a clean idempotent operation.
