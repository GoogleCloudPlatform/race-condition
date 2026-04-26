---
name: contributing
description: >
  Guides the developer workflow for contributing to Race Condition. Use when
  setting up pre-commit hooks, running tests before a PR, understanding code
  style requirements, or preparing a contribution.
---

# Contributing to Race Condition

## First-Time Setup

### Install pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

This installs hooks that run automatically on `git commit`:
- License header checks (Apache 2.0)
- YAML and JSON syntax validation
- Go vet
- Trailing whitespace and EOF fixes

### Verify your environment

```bash
make check-prereqs   # Verify Go, Python, uv, Node.js, Docker
make build           # Build Go services (runs proto generation first)
make test            # Run all tests
```

## Before Every PR

Run these checks. They match what CI runs on GitHub Actions.

### 1. Format code

```bash
make fmt
```

This runs `gofmt -w .` for Go and `uv run ruff format agents/` for Python.

### 2. Lint

```bash
make lint
```

Runs all linters:
- `golangci-lint run ./...` (Go)
- `uv run ruff check agents/` (Python)
- `npx --yes pyright@latest agents/` (Python type checking)
- Pre-commit hooks for YAML and JSON syntax validation

### 3. Run tests

```bash
make test
```

Runs Go tests, Python tests (excluding slow/eval), and web UI tests. Python
tests run without real GCP credentials; `conftest.py` mocks them.

### 4. Check coverage

```bash
make coverage
```

Generates Go and Python coverage reports. Python has a 60% minimum threshold.

## Code Style

### Go

- Format with `gofmt` (enforced by `make fmt`)
- Lint with `golangci-lint`
- Tests use `testify` for assertions and `miniredis` for Redis mocking
- Integration tests are tagged with `Integration` or `Relay` in test names

### Python

- Format with `ruff format`
- Lint with `ruff check`
- Type check with `pyright`
- Tests use `pytest` with `pytest-asyncio` for async tests
- Agent entry point must be `root_agent` in `agent.py`
- Use `google-genai` SDK (not the deprecated `google-generativeai`)

### License headers

All source files must have Apache 2.0 license headers (year 2026, Google LLC).
The pre-commit hook checks this. If missing, add:

```python
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...
```

## PR Process

1. Fork the repo on GitHub.
2. Branch from `main` with a descriptive name.
3. Make your changes following the code style above.
4. Run `make test` and `make lint`. Fix any failures.
5. Commit with clear messages describing what changed and why.
6. Push and open a PR against `main`.
7. Sign the CLA when prompted (first-time contributors only).

PRs are squash-merged. Write a clear PR title and description.

## Test Architecture

| Command | What it runs | Needs infra? |
|---|---|---|
| `make test-go` | `go test ./... -count=1` | No (uses miniredis) |
| `make test-py` | `uv run pytest agents/ -x -q -m "not slow and not integration"` | No (mocks GCP) |
| `make test-web` | `npm test` in admin-dash + tester | No |
| `make eval` | Agent evaluations with real Gemini API | Yes (costs money) |
| `make verify` | lint + unit tests + coverage | No |
| `make verify-full` | verify + integration tests | Yes (needs Redis/Docker) |

## Quick Reference

| Task | Command |
|---|---|
| Format all code | `make fmt` |
| Lint all code | `make lint` |
| Run all tests | `make test` |
| Run only Go tests | `make test-go` |
| Run only Python tests | `make test-py` |
| Generate coverage | `make coverage` |
| Build everything | `make build` |
| Regenerate protobuf | `make proto` |

See [CONTRIBUTING.md](../../../CONTRIBUTING.md) for the full contributing
guide including the CLA process.
