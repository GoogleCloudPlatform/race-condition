# Race Condition -- one-click deploy

This tutorial deploys Race Condition to your own GCP project. It takes
about 15 minutes and runs entirely inside this Cloud Shell session, so
you don't need to install anything locally.

Cost runs about $2-5 per day with the default scale-to-zero sizing. You
can tear it all down whenever with one command (`./scripts/teardown.sh`,
instructions at the bottom). The [README cost note](README.md#cost-note)
has the full breakdown if you want to know where the money goes.

## Step 1: run the deploy script

**Copy** the command below (`Ctrl+C` on Windows/Linux, `Cmd+C` on Mac), then click into the **Cloud Shell terminal on the left** and **paste** it (`Ctrl+V` / `Cmd+V`) and press **Enter**.

```bash
./scripts/deploy.sh
```

The script is interactive — **follow the prompts in the terminal on the left** to complete the deployment. It will ask you to confirm the cost, choose a GCP project, and pick a region. Answer each prompt, and the script handles the rest.

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

When you're done, **Copy** the command below (`Ctrl+C` on Windows/Linux, `Cmd+C` on Mac), then click into the **Cloud Shell terminal on the left** and **paste** it (`Ctrl+V` / `Cmd+V`) and press **Enter**.

```bash
./scripts/teardown.sh
```

The script is interactive — **follow the prompts in the terminal on the left** to complete the teardown. It will ask you to choose a GCP project, pick a region (the same one you deployed to), and type `destroy` to confirm. Answer each prompt, and the script handles the rest. Total wall time is around 3-5 minutes.

What it removes:

- All five Vertex AI Agent Engines (planner, simulator, planner_with_eval, planner_with_memory, simulator_with_failure)
- All Terraform-managed infrastructure: Cloud Run services, Memorystore (Redis), Cloud SQL, Pub/Sub topics, Artifact Registry, IAM bindings, networking, secrets
- Optionally, the Terraform state bucket (`gs://${PROJECT_ID}-tf-state`) — the script asks at the end. Keep it if you might redeploy soon (~free to keep around); delete it for a totally clean slate.

What it leaves alone:

- The GCP project itself — delete it from the [Cloud Console](https://console.cloud.google.com/cloud-resource-manager) if you want every trace gone.
- Artifact Registry images — pennies per month at this scale; kept so a future redeploy is fast.
- Cloud Build history and logs.
