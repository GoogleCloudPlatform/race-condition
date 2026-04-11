# How to Contribute

We'd love to accept your patches and contributions to this project.

## Contributor License Agreement

Contributions to this project must be accompanied by a Contributor License
Agreement (CLA). You (or your employer) retain the copyright to your
contribution; this simply gives us permission to use and redistribute your
contributions as part of the project.

Visit <https://cla.developers.google.com/> to see your current agreements on
file or to sign a new one.

You generally only need to submit a CLA once, so if you've already submitted one
(even if it was for a different project), you probably don't need to do it again.

## Community Guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## How to Contribute

### Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/race-condition.git
   cd race-condition
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b feat/my-change
   ```
4. **Make your changes**, following the code style guidelines below.
5. **Test** your changes (see Testing below).
6. **Commit** your changes using [Conventional Commits](https://www.conventionalcommits.org/) format.
7. **Push** to your fork and **submit a pull request**.

### Code Style

- **Go**: Format with `gofmt`. All Go code must pass `go vet ./...`.
- **Python**: Lint and format with [ruff](https://docs.astral.sh/ruff/). Run `uv run ruff check agents/` and `uv run ruff format --check agents/`.
- **TypeScript / JavaScript**: Format with [Prettier](https://prettier.io/).

### Testing

Before submitting a pull request, run the test suite:

```bash
make test
```

This runs Go tests, Python tests, and linters. Ensure all checks pass before
opening your PR.

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Examples:
- `feat(gateway): add health check endpoint`
- `fix(agents): handle timeout in planner agent`
- `docs: update quickstart instructions`

### Pull Request Process

1. Ensure your PR description clearly describes the problem and solution.
2. Link any related issues using `Closes #123` in the PR description.
3. All CI checks must pass.
4. A project maintainer will review your PR. Please be patient — we review
   contributions as quickly as we can.
5. Once approved, a maintainer will merge your PR.

## Code Reviews

All submissions, including submissions by project members, require review. We
use GitHub pull requests for this purpose. Consult
[GitHub Help](https://help.github.com/articles/about-pull-requests/) for more
information on using pull requests.
