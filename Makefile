# Makefile for n26-devkey-simulation-code/backend
#
# Usage:
#   make proto     — generate protobuf bindings (Go + Python)
#   make test      — run all Go + Python tests
#   make lint      — run Go and Python linters
#   make lint-go   — run golangci-lint only
#   make lint-py   — run ruff only
#   make fmt       — format all code
#   make coverage  — generate coverage reports for Go + Python
#   make eval      — run agent evaluations (requires Gemini API)

.PHONY: test lint lint-go lint-py lint-pyright lint-configs fmt build proto ensure-venv coverage coverage-go coverage-py test-unit-go test-integration-go coverage-ratchet-go coverage-ratchet-py test-web verify worktree-env perf-test perf-diagnostic eval-stress test-e2e-simulation docker-build-all docker-build-go docker-build-py eval

# --- Verify (All Automated Layers) ---
# verify: Layers 1-3 (no infrastructure required)
# verify-full: Layers 1-4 (requires Redis/Docker for integration tests)
verify: lint test-unit-go test-py test-web coverage
	@echo "✅ Layers 1-3 passed (lint, unit tests, coverage)."

verify-full: verify test-integration-go
	@echo "✅ All automated verification layers (1-4) passed."

# --- Venv Bootstrap ---
ensure-venv:
	@if [ ! -x ".venv/bin/python3" ]; then echo "📦 Creating venv..." && uv sync; fi

# --- Proto Generation ---
proto: ensure-venv
	bash scripts/core/generate_proto.sh

# --- Build ---
build: proto
	go build ./...

# --- Test ---
test: test-go test-py test-web

test-go:
	go test ./... -count=1

test-py:
	uv run pytest agents/ -x -q -m "not slow"

test-web:
	@for dir in web/admin-dash web/tester; do \
		if [ -f "$$dir/package.json" ]; then \
			echo "🌐 Testing $$dir..."; \
			(cd $$dir && npm test) || exit 1; \
		fi; \
	done
	@echo "✅ All web UI tests passed."

# --- Agent Evaluations (requires Gemini API) ---
eval:
	uv run pytest agents/ -x -v -m "slow" -o "addopts="

# --- Performance Testing ---
perf-test:
	uv run python scripts/bench/perf_test.py $(PERF_ARGS)

perf-diagnostic:  ## Run performance diagnostic against GATEWAY_URL
	uv run python scripts/bench/perf_diagnostic.py $(PERF_ARGS)

# --- Eval Stress Testing ---
eval-stress:
	uv run python scripts/bench/eval_stress_test.py $(EVAL_STRESS_ARGS)

# --- Concurrency Benchmarking ---
bench-concurrency:
	uv run python scripts/bench/bench_concurrency.py $(BENCH_ARGS)

bench-test:
	uv run pytest scripts/tests/ -v

# --- Scale Testing ---
scale-test:
	uv run python scripts/e2e/e2e_scale_test.py $(SCALE_ARGS)

# --- Lint ---
lint: lint-go lint-py lint-pyright lint-configs

lint-go:
	@command -v golangci-lint >/dev/null 2>&1 || { echo "❌ golangci-lint not found. Install: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"; exit 1; }
	golangci-lint run ./...

lint-py:
	uv run ruff check agents/

lint-pyright:
	npx --yes pyright@latest agents/

lint-configs:
	@echo "🔍 Validating YAML, JSON, and Dockerfile syntax..."
	pre-commit run check-yaml --all-files
	pre-commit run check-json --all-files
	pre-commit run hadolint --all-files
	@echo "✅ All config files valid."

# --- Format ---
fmt: fmt-go fmt-py

fmt-go:
	gofmt -w .

fmt-py:
	uv run ruff format agents/

# --- Coverage ---
coverage: coverage-go coverage-py

coverage-go:
	go test $$(go list ./... | grep -v gen_proto) -coverprofile=coverage.out -count=1 -short
	go tool cover -func=coverage.out
	go tool cover -html=coverage.out -o coverage.html
	@echo "✅ Go coverage report: coverage.html"

coverage-py:
	uv run pytest agents/ -x -q -m "not slow" --cov=agents --cov-report=term-missing --cov-report=html:htmlcov --cov-fail-under=60
	@echo "✅ Python coverage report: htmlcov/index.html"

# --- Test Separation ---
test-unit-go:
	go test ./... -count=1 -short

test-integration-go:
	go test ./... -count=1 -run "Integration|Relay"

# --- Coverage Ratchet ---
coverage-ratchet-go:
	bash scripts/deploy/coverage_ratchet.sh

coverage-ratchet-py:
	uv run pytest agents/ --cov=agents --cov-report=xml -q
	uv run diff-cover coverage.xml --fail-under=80
	@echo "✅ New/changed Python lines have ≥80% coverage"

# --- E2E Simulation Test ---
test-e2e-simulation:
	uv run python scripts/e2e/e2e_simulation_test.py

# --- Worktree Port Management ---
worktree-env:
	@if [ -z "$(SLOT)" ]; then echo "❌ Usage: make worktree-env SLOT=<0-3> [ALLOYDB=true]"; exit 1; fi
	python3 scripts/core/gen_worktree_env.py --slot $(SLOT) $(if $(filter true,$(ALLOYDB)),--use-alloydb,)

# --- Docker Image Builds ---
# Build per-service images using the multi-stage Dockerfile.
# Usage:
#   make docker-build-gateway                    # build single service
#   make docker-build-all                        # build all services
#   make docker-build-gateway TAG=v1.2.3         # custom tag
#   make docker-build-all REGISTRY=my-registry   # custom registry
REGISTRY ?= us-central1-docker.pkg.dev/n26-devkey-simulation-dev/cloudrun
TAG ?= latest

docker-build-%:
	docker buildx build --target $* -t $(REGISTRY)/$*:$(TAG) --load .

docker-build-all: docker-build-gateway docker-build-admin docker-build-tester docker-build-frontend docker-build-runner_autopilot docker-build-runner_cloudrun docker-build-dash

docker-build-go: docker-build-gateway docker-build-admin docker-build-tester docker-build-frontend

docker-build-py: docker-build-runner_autopilot docker-build-runner_cloudrun docker-build-dash
