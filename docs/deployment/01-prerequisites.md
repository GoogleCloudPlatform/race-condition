# Prerequisites

This guide covers everything you need before deploying the simulation platform.
Complete all sections in order -- the find-and-replace checklist at the end is
the most critical step.

## 1. GCP Project Setup

You need **one** GCP project for all runtime services, infrastructure, and
Terraform state:

```bash
gcloud projects create YOUR-PROJECT-ID
gcloud config set project YOUR-PROJECT-ID
```

> **Note:** The team's internal setup uses 4 separate GCP projects (management,
> dev, prod-a, prod-b). This guide simplifies to a single project. If you want
> CI/CD via Cloud Build and Secure Source Manager, you can optionally create a
> second management project -- see the internal
> [Cloud Deployment Guide](../gcp-deployment.md) for that topology.

### Enable billing

Your project requires an active billing account. Link billing via the
[Cloud Console Billing page](https://console.cloud.google.com/billing).

### Set your default project

```bash
gcloud config set project YOUR-CODE-PROJECT-ID
```

## 2. Required Tools

Install the following tools before proceeding:

| Tool | Minimum Version | Install |
| :--- | :--- | :--- |
| Google Cloud SDK | latest | [Install guide](https://cloud.google.com/sdk/docs/install) |
| Terraform | >= 1.5 | [Install guide](https://developer.hashicorp.com/terraform/install) |
| Docker (with buildx) | latest | [Install guide](https://docs.docker.com/get-docker/) |
| Node.js | >= 24 | [Install guide](https://nodejs.org/) |
| Go | >= 1.25 | [Install guide](https://go.dev/dl/) |
| Python | >= 3.13 | Managed via `uv` (below) |
| `uv` | latest | [Install guide](https://docs.astral.sh/uv/getting-started/installation/) |
| `protoc` | latest | [Install guide](https://grpc.io/docs/protoc-installation/) |

Verify key tools:

```bash
gcloud version
terraform version
docker buildx version
node --version
go version
uv --version
protoc --version
```

## 3. Fork and Clone Repositories

The platform consists of three repositories. Fork each to your own source
control, then clone them:

```bash
# Create a working directory
mkdir -p ~/src/your-project && cd ~/src/your-project

# Clone your forks (replace URLs with your fork locations)
git clone <YOUR-BACKEND-REPO-URL> backend
git clone <YOUR-CODE-INFRA-REPO-URL> code-infra
git clone <YOUR-FRONTEND-REPO-URL> frontend
```

| Repository | Contains |
| :--- | :--- |
| `backend` | Go services, Python AI agents, web UIs, Docker build |
| `code-infra` | Terraform infrastructure (IAM, DNS, IAP, Cloud Build) |
| `frontend` | Customer-facing frontend application |

## 4. Authentication

Authenticate with Google Cloud:

```bash
# Interactive login
gcloud auth login

# Application Default Credentials (required for Terraform and SDKs)
gcloud auth application-default login
```

If you are deploying to a project that uses Vertex AI, also set the quota
project:

```bash
gcloud auth application-default set-quota-project YOUR-DEV-PROJECT-ID
```

## 5. Find-and-Replace Checklist

> **This is the most important section.** Every value below is hardcoded in the
> original source. You **must** replace each one with your own project-specific
> value before running Terraform or deploying services. Missing even one will
> cause deployment failures.

### How to use this checklist

1. Work through each row in order.
2. Use your editor's **find-and-replace across files** (e.g., `rg` or IDE
   global search) to locate and replace every occurrence.
3. Check off each row after replacing.

### Project IDs

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 1 | `n26-devkey-simulation-code` | Your management/code project ID | `code-infra/projects/code/variables.tf` (default for `project_id`), `code-infra/projects/code/backups.tf`, `backend/GEMINI.md`, `backend/README.md`, `backend/Makefile`, `backend/go.mod` (Go module path), Go import paths in `cmd/`, `internal/`, `gen_proto/` |
| 2 | `n26-devkey-simulation-dev` | Your dev environment project ID | `code-infra/projects/dev/variables.tf` (default for `project_id`), `code-infra/projects/code/variables.tf` (default for `dev_project_id`), `backend/.env.example`, `backend/.env.dev`, `backend/cloudbuild.yaml` (`_TARGET_PROJECT_ID`), `backend/Makefile` (`REGISTRY`), `code-infra/projects/dev/iam.tf` |
| 3 | `n26-devkey-simulation-prod-a` | Your prod-A project ID (if using) | `code-infra/projects/code/variables.tf` (default for `prod_a_project_id`), `code-infra/projects/prod-a/main.tf` |
| 4 | `n26-devkey-simulation-prod-b` | Your prod-B project ID (if using) | `code-infra/projects/code/variables.tf` (default for `prod_b_project_id`), `code-infra/projects/prod-b/main.tf` |

### Project Numbers

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 5 | `516035864253` | Your management/code project **number** | `code-infra/projects/code/iam.tf` (Cloud Build SAs, SSM service agent SAs, DevConnect SA), `code-infra/projects/code/backups.tf`, `code-infra/projects/code/cloudbuild-backup.yaml`, `backend/scripts/deploy/ssm_pr.sh`, `backend/GEMINI.md`, `backend/docs/contributing.md`, `backend/docs/guides/a2a-implementation-guide.md`, `backend/iam_policy.json` |
| 6 | `493657444235` | Your dev environment project **number** | `code-infra/projects/dev/iam.tf` (compute SA), `backend/.env.dev` (internal Cloud Run URLs, Agent Engine URLs, IAP client ID), `backend/iam_policy.json`, `backend/internal/hub/switchboard_test.go` |

> **How to find your project number:**
> ```bash
> gcloud projects describe YOUR-PROJECT-ID --format='value(projectNumber)'
> ```

### Domain and DNS

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 7 | `keynote2026.cloud-demos.goog` | Your base domain | `code-infra/projects/code/dns.tf`, `code-infra/projects/code/outputs.tf`, `code-infra/projects/dev/dns.tf`, `code-infra/projects/dev/iap.tf` (`domain_suffix`), `code-infra/projects/dev/outputs.tf`, `backend/.env.dev` (all service URLs, CORS origins), `backend/cloudbuild.yaml` (`_DOMAIN`), `backend/docs/gcp-deployment.md`, `backend/scripts/deploy/deploy.py`, `backend/scripts/tests/test_deploy.py`, `backend/web/tester/src/url.test.ts`, various `backend/docs/plans/` files |
| 8 | `dev.keynote2026.cloud-demos.goog` | `dev.YOUR-DOMAIN` | `code-infra/projects/dev/dns.tf` (`dns_name`), `code-infra/projects/dev/iap.tf` (`domain_suffix`), `code-infra/projects/code/dns.tf` (NS delegation record), `backend/.env.dev` (service URLs) |

> **Note:** If you replace the base domain (`keynote2026.cloud-demos.goog`),
> the `dev.*` subdomain references will be covered automatically in most cases.
> Verify with a global search after replacing.

### Infrastructure Names

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 9 | `n26-devkey-simulation-terraform-state-central` | Your Terraform state GCS bucket name | `code-infra/projects/code/backend.tf`, `code-infra/projects/dev/backend.tf` |
| 10 | `n26-ssm-central` | Your SSM instance name | `code-infra/projects/code/main.tf` (`instance_id`), `code-infra/scripts/sync_ssm_settings.sh`, `code-infra/scripts/sync_ssm_settings_central.sh`, `code-infra/projects/code/backups.tf`, `code-infra/projects/code/cloudbuild-backup.yaml`, `code-infra/README.md`, `backend/GEMINI.md`, `backend/scripts/deploy/ssm_pr.sh`, `backend/docs/contributing.md` |
| 11 | `us-central1-docker.pkg.dev/n26-devkey-simulation-dev/cloudrun` | Your Artifact Registry path | `backend/Makefile` (`REGISTRY` variable), `backend/cloudbuild.yaml` (constructed from `_TARGET_PROJECT_ID`) |

### Artifact Registry Repository

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 12 | `cloudrun` | Your Artifact Registry Docker repo name (if different) | `backend/Makefile`, `backend/cloudbuild.yaml`, `code-infra/projects/dev/` (Terraform creates the AR repo) |

### Service Account Names

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 13 | `n26-agent-engine-sa` | Your Agent Engine service account ID | `code-infra/projects/dev/iam.tf` (`account_id`, `agent_engine_sa` local) |

### IAP Domain Restrictions

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 14 | `domain:google.com` | Your organization's domain(s) | `code-infra/projects/dev/iap.tf` (IAP access binding members) |
| 15 | `domain:cloud-demos.goog` | Your organization's domain (or remove) | `code-infra/projects/dev/iap.tf` (IAP access binding members) |
| 16 | `domain:northkingdom.com` | Your partner domain (or remove) | `code-infra/projects/dev/iap.tf` (IAP access binding members) |

### User Email Lists

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 17 | All `user:*@google.com` entries | Your team's email addresses | `code-infra/projects/code/variables.tf` (all `*_writers`, `*_readers`, `infra_admins` variables), `code-infra/projects/dev/iam.tf` (SA user bindings) |
| 18 | All `user:*@cloud-demos.goog` entries | Your team's email addresses | `code-infra/projects/code/variables.tf` (all user list variables) |
| 19 | All `user:*@northkingdom.com` entries | Your team's email addresses (or remove) | `code-infra/projects/code/variables.tf` (`frontend_writers`, `backend_readers`) |

### Go Module Path

| # | Value to Find | Replace With | Files Where It Appears |
| :--- | :--- | :--- | :--- |
| 20 | `github.com/cwest/n26-devkey-simulation-code/backend` | Your Go module path | `backend/go.mod`, all `*.go` files in `cmd/`, `internal/`, `gen_proto/` (import paths) |

> **Tip:** After updating `go.mod`, run `go mod tidy` to validate the module
> path. For Go import paths, use your editor's global find-and-replace.

### Summary Count

**Total items: 20** covering project IDs, project numbers, domain names,
infrastructure names, service accounts, IAP domains, user emails, and the Go
module path.

### Verification

After completing all replacements, verify nothing was missed:

```bash
# From your project root, search for any remaining original values
rg "n26-devkey-simulation" --type-not gitconfig
rg "516035864253"
rg "493657444235"
rg "keynote2026.cloud-demos.goog"
rg "n26-ssm-central"
rg "github.com/cwest/"
```

Each command should return zero results (excluding this documentation file and
git metadata). If any results appear, update those files before proceeding.

---

**Next:** [02 - Infrastructure Setup](02-infrastructure.md)
