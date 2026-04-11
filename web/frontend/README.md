# Race Condition: Frontend

This repository contains the frontend application for the
Race Condition project.

## Prerequisites

- NodeJS + npm
- Python >= 3.9
- `pre-commit` (Install via `pip install pre-commit` or
  `brew install pre-commit`)
- Google Cloud SDK (`gcloud`) authenticated.
- SSH Key (Ed25519 recommended).

## Setup

Copy the example environment file and fill in your values:
```bash
cp .env.example .env
```

## Install dependencies
```bash
npm install
```

## Running the front end
```bash
npm run start
```

## Development Workflow

We follow professional software development practices to ensure code quality and
security.

### 1. Local Environment Setup

**Mandatory**: All commits must be cryptographically signed, and pre-commit
hooks must be installed.

1. **Initialize Git Configuration**: Run the provided setup script once to
   configure your local signing key, credential helpers, and pre-commit hooks:

   ```bash
   ./scripts/setup_git.sh
   ```

2. **Verify Configuration**: Ensure `commit.gpgsign` is set to `true`:

   ```bash
   git config --list | grep gpg
   ```

### 2. Branching Strategy

- **Main Branch**: The `main` branch is protected and contains production-ready
  code.
- **Feature Branches**: All development must occur on topic branches named
  `topic/{short-name}`.
- **Atomic Commits**: Keep commits small, focused, and descriptive using
  [Conventional Commits](https://www.conventionalcommits.org/).

### 3. Pull Requests & Code Review

- **Submission**: Once your feature is complete, push your branch and open a
  Pull Request (PR) against `main`.
- **Pull Requests & Code Review**: A mandatory process. Every change must be
  submitted via a PR, reviewed and approved by maintainers, and pass CI checks.
  - **Automated Enforcement**: Branch protection rules on `main` mandate that
    all changes are submitted via PRs, require at least one approval, and
    enforce a linear Git history.
  - **Squash-and-Merge**: All pull requests must be **Squashed and Merged** to
    ensure a clean and readable history on the `main` branch. Individual commits
    on feature branches should still be atomic and signed.
- **CI/CD**: Ensure all automated checks pass before requesting a review.

## Source Code Headers

Every file containing source code must include copyright and license
information. This includes any JS/CSS files that you might be serving out to
browsers. (This is to help well-intentioned people avoid accidental copying that
doesn't comply with the license.)

Apache header:

```text
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

## Notification Settings

To stay informed about project activity, ensure your notification settings are
configured:

1. **Watch Repository**: Click "Watch" on the SSM Console to receive email
   updates for PRs and issues.
2. **Pull Request Alerts**: Subscribing to repository movements ensures you are
   alerted when reviews are needed.
