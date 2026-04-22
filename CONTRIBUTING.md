# How to Contribute

Thanks for your interest in **Race Condition**! We welcome contributions of
all sizes — bug fixes, documentation improvements, new features, and ideas.

## Contributor License Agreement

Contributions to this project must be accompanied by a Contributor License
Agreement (CLA). You (or your employer) retain the copyright to your
contribution; this simply gives us permission to use and redistribute your
contributions as part of the project.

Visit <https://cla.developers.google.com/> to see your current agreements on
file or to sign a new one.

You generally only need to submit a CLA once, so if you've already submitted
one (even for a different Google open-source project), you probably don't need
to do it again.

## Community Guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/)
and the [Contributor Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- 🐛 **[Report a bug](../../issues/new?template=bug_report.md)** — something
  is broken or behaves unexpectedly.
- 💡 **[Request a feature](../../issues/new?template=feature_request.md)** —
  propose a new capability before building it.
- 📝 **Improve the documentation** — typos, missing pieces, unclear sections.
- 🔧 **Fix an issue** — pick something from the [open issues](../../issues)
  and submit a pull request.

For larger changes, please **open an issue first** to discuss the approach.
This avoids wasted effort if a maintainer would have steered you a different
direction.

## Submitting a pull request

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/race-condition.git
   cd race-condition
   ```
3. **Create a topic branch** from `main`:
   ```bash
   git checkout -b feat/my-change
   ```
4. **Set up your environment** (see [`README.md`](README.md) → *Quickstart*).
5. **Make your change**, following the code style guidelines below.
6. **Add or update tests** for any behavior change.
7. **Run the full test suite locally**:
   ```bash
   make test
   make lint
   ```
8. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/)
   format (see below).
9. **Push** to your fork and **open a pull request** against `main`.
10. Address review feedback. CI must be green and CODEOWNERS must approve
    before a maintainer merges your PR (squash-merged).

### Code style

- **Go**: format with `gofmt`. All Go code must pass `go vet ./...` and
  `golangci-lint run ./...`.
- **Python**: lint and format with [ruff](https://docs.astral.sh/ruff/). Run
  `uv run ruff check agents/` and `uv run ruff format --check agents/`.
- **TypeScript / JavaScript**: format with [Prettier](https://prettier.io/);
  follow the existing style in each `web/*` workspace.
- **License headers**: every source file needs an Apache-2.0 license header.
  CI enforces this with [`addlicense`](https://github.com/google/addlicense).

### Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`,
`build`, `ci`. Examples:

- `feat(gateway): add health-check endpoint`
- `fix(agents/planner): handle timeout when calling traffic enrichment`
- `docs(readme): clarify quickstart prerequisites`

### Sign your commits

Pull requests must be signed (SSH or GPG). See GitHub's guide on
[signing commits](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).

## Reporting security vulnerabilities

**Do not file public issues for security problems.** See [`SECURITY.md`](SECURITY.md)
for the private disclosure process.

## Forking and deriving

Forks are encouraged — fork freely to study, learn, build derivatives, or
maintain your own variant. The Apache-2.0 license permits commercial and
private use. Just keep the license headers and `LICENSE` file intact.

## Code reviews

All submissions, including those from project members, require review.
Maintainers aim to respond to PRs within a few business days. If your PR has
been quiet for a week, it's fair to ping the thread.

Thanks again for contributing!
