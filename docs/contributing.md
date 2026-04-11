# How to Contribute

We would love to accept your patches and contributions to this project. To
maintain code quality and security, we follow a professional development
workflow.

## Before you begin

### Sign our Contributor License Agreement

Contributions to this project must be accompanied by a
[Contributor License Agreement](https://cla.developers.google.com/about) (CLA).
You (or your employer) retain the copyright to your contribution; this simply
gives us permission to use and redistribute your contributions as part of the
project.

Visit <https://cla.developers.google.com/> to see your current agreements or to
sign a new one.

### Review our Community Guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## Development Process

### 1. Cryptographic Signing (Mandatory)

All commits to this project must be cryptographically signed. This is enforced
by Secure Source Manager.

- **Setup**: Run `./scripts/deploy/setup_git.sh` in the repository root to configure
  your local environment.
- **Verification**: Ensure your SSH public key is added to your Secure Source
  Manager profile.

### 2. Branching and Pull Requests

This project uses a **three-branch model**: `topic/* -> dev -> main`.

- **`dev`** is the integration branch where topic branches accumulate for
  frontend team validation.
- **`main`** is the stable/release branch, updated only via promotion PRs
  from `dev`.

- **Topic Branches**: Always sync with the latest `dev` before branching:

  ```bash
  git checkout dev
  git pull --rebase origin dev
  git checkout -b topic/{short-name}
  ```

- **Promotion to Main**: When the frontend team validates accumulated changes
  on `dev`, create a promotion PR:

  ```bash
  scripts/deploy/ssm_pr.sh "Promote dev to main" "Description" main
  ```

- **SSH Key Verification**: Ensure your SSH public key is added to the
  [SSM Console](https://n26-ssm-central-516035864253.us-central1.sourcemanager.dev/user/settings/keys)
  to verify signatures in the UI.
  - **Mandatory PRs**: Direct pushes to `main` and `dev` are blocked.
  - **Linear History**: Only squash or rebase merges are allowed.
  - **Required Reviews**: At least one approval is mandatory.

### 3. Code Reviews

All submissions, including submissions by project members, require review. A
maintainer's approval is required before a PR can be merged.

**Mandatory Merge Strategy**: All pull requests (both `topic->dev` and
`dev->main`) must be **squash merged**. This ensures both `dev` and `main`
branch histories remain concise and readable.

### 4. Stay Informed (Notifications)

Secure Source Manager notifications are per-user and disabled by default. To
receive alerts for Pull Request events and Issues:

1. Open the
   [SSM Instance Settings](https://n26-ssm-central-516035864253.us-central1.sourcemanager.dev/user/settings/notification-settings).
2. Enable **Email Notifications**.
3. Check **Pull request notifications** and **Issue notifications**.
4. Click **Update**.

## Repository Administrator Guide

### Enforced Branch Protections

The following rules are enforced on the `main` and `dev` branches via API
(managed by `sync_ssm_settings.sh` in the `code-infra` repository):

**`main` branch:**

- **Require Pull Request**: True
- **Minimum Approvals**: 1
- **Require Linear History**: True
- **Require Comments Resolved**: True

**`dev` branch (backend repo only):**

- **Require Pull Request**: True
- **Minimum Approvals**: 0
- **Require Linear History**: True
- **Require Comments Resolved**: True

### Data Loss Prevention (DLP)

DLP must be enabled manually in the Secure Source Manager Console:

1. Navigate to the repository in the
   [GCP Console](https://console.cloud.google.com/security/source-manager).
2. Go to **Settings**.
3. Toggle **Data Loss Prevention** to **ON**.

## Licensing

By contributing to this project, you agree that your contributions will be
licensed under the project's Apache 2.0 License. All source files must include
the standard Apache header.
