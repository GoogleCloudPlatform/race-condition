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

- **Setup**: Run `./scripts/setup_git.sh` in the repository root to configure
  your local environment.
- **Verification**: Ensure your SSH public key is added to your Secure Source
  Manager profile.

### 2. Branching and Pull Requests

- **Atomicity**: Commits should be atomic and follow
  [Conventional Commits](https://www.conventionalcommits.org/).
- **Topic Branches**: Create branches from `main` using the format
  `topic/{short-name}`.
- **Pull Requests (Enforced)**:
  - **Mandatory PRs**: Direct pushes to `main` are blocked.
  - **Linear History**: Only squash or rebase merges are allowed.
  - **Required Reviews**: At least one approval is mandatory.

### 3. Code Reviews

All submissions, including submissions by project members, require review. A
maintainer's approval is required before a PR can be merged.

**Mandatory Merge Strategy**: All pull requests must be **squash merged**. This
ensures the `main` branch history remains concise and readable.

## Repository Administrator Guide

Secure Source Manager (SSM) repository settings are synchronized via the
`scripts/sync_ssm_settings.sh` tool.

### Enforced Branch Protections

The following rules are enforced on the `main` branch via API:

- **Require Pull Request**: True
- **Minimum Approvals**: 1
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
