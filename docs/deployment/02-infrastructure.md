# Infrastructure Setup

This guide walks through provisioning GCP infrastructure using the `code-infra`
Terraform, adapted for a single-project deployment.

> **Previous step:** [Prerequisites](01-prerequisites.md)

## 1. Overview

The existing Terraform in `code-infra/` uses a multi-project layout:

| Directory | Purpose | Single-project action |
| :--- | :--- | :--- |
| `projects/code/` | SSM source control, KMS, Cloud Build triggers, backup automation | **Skip entirely** -- these are team-specific resources |
| `projects/dev/` | Cloud Run infrastructure, networking, backing services, IAP | **Use and adapt** for your single project |

For a single-project deploy you only need `projects/dev/`. All resources
(Artifact Registry, Cloud Run, Redis, AlloyDB, load balancer) will live in your
one project.

## 2. Create Terraform State Bucket

Terraform needs a GCS bucket to store remote state. Create one manually before
running any Terraform commands:

```bash
gsutil mb -l us-central1 gs://YOUR-TERRAFORM-STATE-BUCKET/
gsutil versioning set on gs://YOUR-TERRAFORM-STATE-BUCKET/
```

Then update `code-infra/projects/dev/backend.tf` to point to your bucket:

```hcl
terraform {
  backend "gcs" {
    bucket = "YOUR-TERRAFORM-STATE-BUCKET"
    prefix = "terraform/state/code-infra/dev"
  }
}
```

The original file uses `n26-devkey-simulation-terraform-state-central` --
replace this with your bucket name.

## 3. Update Terraform Variables

### Review `variables.tf`

The file defines four variables:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `project_id` | `string` | `n26-devkey-simulation-dev` | Your GCP project ID |
| `region` | `string` | `us-central1` | Deployment region |
| `iap_oauth2_client_id` | `string` | (none) | OAuth 2.0 client ID for IAP |
| `iap_oauth2_client_secret` | `string` (sensitive) | (none) | OAuth 2.0 client secret for IAP |

### Create `terraform.tfvars`

Create `code-infra/projects/dev/terraform.tfvars`:

```hcl
project_id              = "your-project-id"
region                  = "us-central1"
iap_oauth2_client_id     = ""
iap_oauth2_client_secret = ""
```

> **Note:** The IAP OAuth credentials are created later during the
> [Domain & SSL Setup](05-domain-and-auth.md) step. Leave them as empty strings for
> now -- you will do a two-pass apply (see Section 6).

### Update the provider block

In `main.tf`, the provider has hardcoded values. Update them to use variables:

```hcl
provider "google" {
  project = var.project_id
  region  = var.region
}
```

## 4. Terraform Resources Walkthrough

Each `.tf` file provisions a specific category of resources. Here is what each
one does and whether it is required for a single-project deployment.

### `main.tf` -- API Enablement & Core Resources

**Status: Required**

Enables the GCP APIs needed by the platform:

- `aiplatform.googleapis.com` -- Vertex AI / Agent Engine
- `generativelanguage.googleapis.com` -- Gemini API access
- `pubsub.googleapis.com` -- Pub/Sub messaging
- `redis.googleapis.com` -- Memorystore for Redis
- `servicenetworking.googleapis.com` -- Private services access (VPC peering)
- `dns.googleapis.com` -- Cloud DNS
- `compute.googleapis.com` -- Compute Engine (load balancer, NAT)
- `alloydb.googleapis.com` -- AlloyDB for PostgreSQL
- `vpcaccess.googleapis.com` -- Serverless VPC Access

Also creates:

- **Staging bucket** (`google_storage_bucket.staging`) -- used for Agent Engine
  deployments. Update the name to match your project.
- **Artifact Registry** (`google_artifact_registry_repository.cloudrun`) --
  Docker registry for Cloud Run container images.

**Changes needed:** Update the staging bucket `name` to be unique (e.g.,
`your-project-id-staging`).

### `networking.tf` -- VPC, Subnets, NAT, PSC

**Status: Required**

Creates the networking foundation that Cloud Run services, Redis, and AlloyDB
need to communicate:

| Resource | Purpose |
| :--- | :--- |
| `google_compute_network.main_vpc` | Custom VPC network |
| `google_compute_subnetwork.serverless_subnet` | Subnet for Serverless VPC Access (`10.8.0.0/28`) |
| `google_compute_global_address.private_ip_alloc` | IP allocation for VPC peering (Redis/AlloyDB) |
| `google_service_networking_connection.private_vpc_connection` | Private services access peering |
| `google_vpc_access_connector.connector` | Serverless VPC Access connector for Cloud Run |
| `google_compute_network_attachment.re_psc_attachment` | PSC network attachment for Agent Engine |
| IAM grants for Vertex AI service agents | Network admin permissions for PSC |
| `google_compute_router.router` + `google_compute_router_nat.nat` | Cloud NAT for outbound internet from VPC |

Cloud NAT is critical -- Cloud Run services with `vpc-egress=all-traffic` need
it to reach other Cloud Run services via their `.run.app` URLs.

**Changes needed:** None (uses `var.region` and `var.project_id` already).

### `backing_services.tf` -- Redis, Pub/Sub, AlloyDB

**Status: Required**

Provisions the stateful backing services:

| Resource | Purpose | Backend env var |
| :--- | :--- | :--- |
| `google_pubsub_topic.collector_telemetry` | Telemetry collection topic | `PUBSUB_TOPIC_ID` |
| `google_redis_instance.simulation_cache` | Session management and gateway pub/sub | `REDIS_ADDR` |
| `google_alloydb_cluster.simulation_db_cluster` | Agent Memory AlloyDB cluster (`am-cluster` for `planner_with_memory`) | `ALLOYDB_*` vars |
| `google_alloydb_instance.simulation_db_primary` | AlloyDB primary instance (2 vCPU) | -- |
| `google_pubsub_topic.specialist_orchestration` | Specialist agent orchestration topic | -- |
| `google_pubsub_subscription.gateway_push_orchestration` | Push subscription to gateway endpoint | -- |
| `google_service_account_iam_member.pubsub_token_creator` | Allows Pub/Sub SA to create OIDC tokens | -- |

> **Note:** The `runner-db-cluster` AlloyDB cluster (previously used for runner
> durable sessions) has been removed. Only the `am-cluster` (Agent Memory for
> `planner_with_memory`) remains.

> **Security note:** The `am-cluster` AlloyDB cluster uses a hardcoded dummy
> password (`DevPassword123!`). For production use, replace this with a Secret
> Manager reference or generate a random password via Terraform.

**Changes needed:**
- The push subscription endpoint references `local.domain_suffix`
  (`gateway.dev.keynote2026.cloud-demos.goog`). Update this to match your domain
  once DNS is configured, or comment it out until step 5 is complete.
- The push subscription uses `var.iap_oauth2_client_id` as the OIDC audience --
  this will be empty on the first pass. Comment out the push subscription until
  IAP is configured.

### `dns.tf` -- Cloud DNS Managed Zone

**Status: Required if using a custom domain, optional otherwise**

Creates a Cloud DNS managed zone for the `dev.keynote2026.cloud-demos.goog`
domain.

```hcl
resource "google_dns_managed_zone" "dev_keynote2026" {
  name        = "dev-keynote2026-cloud-demos-goog"
  dns_name    = "dev.keynote2026.cloud-demos.goog."
  description = "Managed zone for Keynote 2026 dev environment"
}
```

**Changes needed:** Replace the zone name and DNS name with your own domain.
If you do not have a custom domain, you can comment this file out and access
services via their `.run.app` URLs directly (though IAP will not work without
a domain).

### `iap.tf` -- Load Balancer, NEGs, IAP, SSL

**Status: Required for custom domain + authentication, optional for
`.run.app`-only access**

This is the largest and most complex file. It creates:

| Resource Category | Resources | Purpose |
| :--- | :--- | :--- |
| **Serverless NEGs** | One per service (admin, gateway, tester, runner, dash) | Route traffic to Cloud Run services |
| **Backend services** | One per service, with IAP enabled | Per-service IAP enforcement |
| **IAP access bindings** | `roles/iap.httpsResourceAccessor` per backend | Controls who can access each service |
| **URL map** | Host-based routing (`{service}.{domain}`) | Routes requests to correct backend |
| **SSL certificates** | 2 managed certs (5 domains max per cert) | HTTPS termination |
| **HTTPS proxy + forwarding rule** | Global load balancer | Ingress |
| **DNS A records** | One per service | Points service subdomains to LB IP |

> **Important:** IAP requires OAuth 2.0 client credentials. You must either:
> 1. Create the OAuth client first (see [Domain & SSL Setup](05-domain-and-auth.md))
>    and populate `iap_oauth2_client_id` / `iap_oauth2_client_secret` before
>    applying, or
> 2. Do a **two-pass Terraform apply**: first apply without `iap.tf` (rename it
>    to `iap.tf.disabled`), then re-enable it after creating the OAuth client.

**Changes needed:**
- Update `local.domain_suffix` to your domain.
- Update `local.services` map if you are deploying a subset of services.
- Update the IAP access binding `members` list -- remove `domain:google.com`,
  `domain:cloud-demos.goog`, and `domain:northkingdom.com`, and add your own
  users or domain (e.g., `user:you@example.com` or `domain:example.com`).
- Update SSL certificate domain lists to match your domain.

### `iam.tf` -- Service Accounts & IAM Bindings

**Status: Required, but needs significant adaptation**

Creates service accounts and IAM bindings. This file has the most changes needed
for a single-project deployment.

#### Service accounts created

| Resource | Purpose |
| :--- | :--- |
| `google_service_account.agent_engine` | SA for Agent Engine (Reasoning Engine) operations |
| `google_project_service_identity.iap_sa` | IAP service identity (auto-managed by GCP) |

#### What to keep

These bindings are needed regardless of project layout:

- **IAP invoker** (`iap_invoker`) -- lets IAP SA invoke Cloud Run services
- **Compute SA roles** -- `run.invoker`, `storage.admin`, `artifactregistry.admin`,
  `run.admin`, `iam.serviceAccountUser`, `cloudbuild.builds.builder`,
  `pubsub.publisher` -- needed for Cloud Run deployment and service-to-service
  communication
- **Agent Engine SA roles** -- `pubsub.publisher`, `aiplatform.user`,
  `logging.logWriter`, `viewer`, `serviceusage.serviceUsageConsumer`

#### What to remove or modify

- **Cross-project Cloud Build permissions** (`build_ar_admin`, `build_run_admin`,
  `build_sa_viewer`, `build_sa_user`) -- these grant the `code` project's Cloud
  Build SA access to the `dev` project. **Remove these entirely** for a
  single-project deploy. If you use Cloud Build, grant permissions to your own
  project's Cloud Build SA instead.

- **`local.compute_sa`** -- hardcoded to
  `493657444235-compute@developer.gserviceaccount.com` (the original dev
  project's compute SA). **Replace** with your project's compute SA:
  `serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com`

- **`local.build_sa`** -- hardcoded to
  `516035864253@cloudbuild.gserviceaccount.com` (the code project's Cloud Build
  SA). **Remove** or replace with your project's Cloud Build SA.

- **Agent Engine SA user bindings** (`agent_engine_sa_user`) -- the `for_each`
  list includes specific user emails (`caseywest@google.com`,
  `caseyw@cloud-demos.goog`). **Replace these with your own user email(s)** and
  your project's compute SA.

#### Finding your project number

```bash
gcloud projects describe YOUR-PROJECT-ID --format='value(projectNumber)'
```

Use this number to construct the compute SA email:
`YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com`

### `secrets.tf` -- Secret Manager

**Status: Required for IAP**

Stores the IAP OAuth credentials in Secret Manager and grants the compute SA
access to read them:

| Resource | Purpose |
| :--- | :--- |
| `google_secret_manager_secret.iap_client_id` | Stores the OAuth client ID |
| `google_secret_manager_secret.iap_client_secret` | Stores the OAuth client secret |
| Secret IAM members | Grants compute SA `secretmanager.secretAccessor` |

Cloud Run services read these secrets at runtime to validate IAP tokens.

**Changes needed:** None beyond the `local.compute_sa` fix from `iam.tf`.

### `outputs.tf` -- Terraform Outputs

**Status: Required (no changes needed)**

Exports values you will need for later configuration steps. See Section 7 for
the full mapping.

## 5. Adapt IAM for Single Project

This section consolidates the IAM changes from Section 4 into a concrete
checklist.

### Update `locals` block in `iam.tf`

Replace the hardcoded service accounts:

```hcl
locals {
  # Replace with your project number (from: gcloud projects describe ...)
  compute_sa      = "serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com"
  # Remove build_sa entirely, or set to your own Cloud Build SA
  # build_sa      = "serviceAccount:YOUR-PROJECT-NUMBER@cloudbuild.gserviceaccount.com"
  agent_engine_sa = "serviceAccount:n26-agent-engine-sa@${var.project_id}.iam.gserviceaccount.com"
}
```

### Remove cross-project Cloud Build resources

Delete or comment out these resource blocks:

- `google_project_iam_member.build_ar_admin`
- `google_project_iam_member.build_run_admin`
- `google_project_iam_member.build_sa_viewer`
- `google_project_iam_member.build_sa_user`

### Update Agent Engine SA user bindings

Replace the `for_each` set with your own principals:

```hcl
resource "google_service_account_iam_member" "agent_engine_sa_user" {
  for_each = toset([
    local.compute_sa,
    "user:your-email@example.com",
  ])
  service_account_id = google_service_account.agent_engine.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}
```

### Update IAP access members

In `iap.tf`, replace the access binding members:

```hcl
members = [
  "user:your-email@example.com",
  # "domain:your-domain.com",  # or use domain-wide access
  local.compute_sa,
]
```

## 6. Apply Terraform

### First pass (without IAP)

If you do not have OAuth credentials yet, disable IAP-dependent resources:

```bash
cd code-infra/projects/dev

# Temporarily disable IAP and its dependencies
mv iap.tf iap.tf.disabled
mv secrets.tf secrets.tf.disabled

# Also comment out the push subscription in backing_services.tf
# (it references IAP OAuth client ID for OIDC audience)

terraform init
terraform plan    # Review carefully
terraform apply
```

### Second pass (with IAP)

After creating OAuth credentials (see [Domain & SSL Setup](05-domain-and-auth.md)):

```bash
cd code-infra/projects/dev

# Re-enable IAP resources
mv iap.tf.disabled iap.tf
mv secrets.tf.disabled secrets.tf

# Update terraform.tfvars with real OAuth credentials
# iap_oauth2_client_id     = "YOUR-CLIENT-ID.apps.googleusercontent.com"
# iap_oauth2_client_secret = "YOUR-CLIENT-SECRET"

# Uncomment push subscription in backing_services.tf

terraform plan    # Review the new IAP resources
terraform apply
```

### Full apply (if you have OAuth credentials ready)

If you already have OAuth credentials:

```bash
cd code-infra/projects/dev
terraform init
terraform plan    # Review all resources
terraform apply
```

## 7. Capture Outputs

After a successful apply, capture the Terraform outputs:

```bash
terraform output
```

### Output-to-env-var mapping

| Terraform Output | Backend `.env` Variable | Format / Notes |
| :--- | :--- | :--- |
| `redis_host` | `REDIS_ADDR` | Append `:6379` -- e.g., `10.x.x.x:6379` |
| `redis_port` | (included in `REDIS_ADDR`) | Default is `6379` |
| `pubsub_topic` | `PUBSUB_TOPIC_ID` | Use just the topic name (e.g., `collector-telemetry`), not the full resource ID |
| `alloydb_ip_address` | AlloyDB connection vars | Used in simulation database configuration |
| `vpc_connector_id` | (used in Cloud Run deploy commands) | Passed as `--vpc-connector` flag |
| `dev_zone_name_servers` | (DNS configuration) | Point your domain registrar's NS records here |
| `lb_ip` | (DNS A records) | The global load balancer IP -- covered in [Domain & SSL Setup](05-domain-and-auth.md) |
| `service_urls` | (reference) | Map of service name to `https://{service}.{domain}` URLs |

### Save outputs for later steps

```bash
# Save to a file for reference during deployment
terraform output -json > ../../../backend/terraform-outputs.json

# Or capture specific values
export REDIS_HOST=$(terraform output -raw redis_host)
export REDIS_PORT=$(terraform output -raw redis_port)
export REDIS_ADDR="${REDIS_HOST}:${REDIS_PORT}"
export VPC_CONNECTOR=$(terraform output -raw vpc_connector_id)
export LB_IP=$(terraform output -raw lb_ip)
```

These values will be used when configuring the backend `.env` file in the
[Backend Services](03-backend-services.md) step.

---

> **Next step:** [Backend Services](03-backend-services.md)
