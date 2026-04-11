# Makefile for Race Condition
# Run `make help` for available targets.

# Load .env if it exists (port assignments, GCP config, etc.)
-include .env
export

.PHONY: init check-prereqs help test lint lint-go lint-py lint-pyright lint-configs fmt build proto ensure-venv coverage coverage-go coverage-py test-unit-go test-integration-go test-web verify perf-test perf-diagnostic eval-stress test-e2e-simulation docker-build-all docker-build-go docker-build-py eval start stop restart

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Process Management ---
# Lifecycle is managed by scripts/core/sim.py (single source of truth).
# See: uv run start --help, uv run stop --help
start: ## Start all services via Honcho
	@uv run start --skip-tests

stop: ## Stop all services and free ports
	@uv run stop

restart: ## Restart all services
	@uv run restart --skip-tests

# --- Verify (All Automated Layers) ---
# verify: Layers 1-3 (no infrastructure required)
# verify-full: Layers 1-4 (requires Redis/Docker for integration tests)
verify: lint test-unit-go test-py test-web coverage ## Run lint, unit tests, and coverage (no infra needed)
	@echo "✅ Layers 1-3 passed (lint, unit tests, coverage)."

verify-full: verify test-integration-go ## Run all verification layers (requires Redis/Docker)
	@echo "✅ All automated verification layers (1-4) passed."

# --- Venv Bootstrap ---
ensure-venv:
	@if [ ! -x ".venv/bin/python3" ]; then echo "📦 Creating venv..." && uv sync; fi

# --- Proto Generation ---
proto: ensure-venv ## Generate protobuf bindings (Go + Python)
	bash scripts/core/generate_proto.sh

# --- Build ---
build: proto ## Build all Go binaries
	go build ./...

# --- Test ---
test: test-go test-py test-web ## Run all tests (Go + Python + Web)

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
eval: ## Run agent evaluations (requires Gemini API)
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
lint: lint-go lint-py lint-pyright lint-configs ## Run all linters (Go + Python + configs)

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
	@echo "✅ All config files valid."

# --- Format ---
fmt: fmt-go fmt-py ## Format all code (Go + Python)

fmt-go:
	gofmt -w .

fmt-py:
	uv run ruff format agents/

# --- Coverage ---
coverage: coverage-go coverage-py ## Generate coverage reports (Go + Python)

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

# --- E2E Simulation Test ---
test-e2e-simulation:
	uv run python scripts/e2e/e2e_simulation_test.py

# --- Docker Image Builds ---
# Build per-service images using the multi-stage Dockerfile.
# Usage:
#   make docker-build-gateway                    # build single service
#   make docker-build-all                        # build all services
#   make docker-build-gateway TAG=v1.2.3         # custom tag
#   make docker-build-all REGISTRY=my-registry   # custom registry
REGISTRY ?= race-condition
TAG ?= latest

docker-build-%:
	docker buildx build --target $* -t $(REGISTRY)/$*:$(TAG) --load .

docker-build-all: docker-build-gateway docker-build-admin docker-build-tester docker-build-frontend docker-build-runner_autopilot docker-build-runner_cloudrun docker-build-dash ## Build all Docker images

docker-build-go: docker-build-gateway docker-build-admin docker-build-tester docker-build-frontend

docker-build-py: docker-build-runner_autopilot docker-build-runner_cloudrun docker-build-dash


# resolves the target the same way the sync script does.
	if [ -f .git ]; then \
		_GIT_COMMON=$$(git rev-parse --git-common-dir); \
		_MAIN_REPO=$$(cd "$$_GIT_COMMON/.." && pwd); \
		echo "$$(cd "$$_MAIN_REPO/.." && pwd)/race-condition"; \
	else \
		echo "$$(cd .. && pwd)/race-condition"; \
	fi')


# --- Developer Experience ---
PREREQS := go node uv docker

check-prereqs: ## Verify all prerequisites are installed
	@echo "Checking prerequisites..."
	@fail=0; \
	for cmd in $(PREREQS); do \
		if command -v $$cmd >/dev/null 2>&1; then \
			printf "  ✅ %-10s %s\n" "$$cmd" "$$($$cmd --version 2>/dev/null | head -1)"; \
		else \
			printf "  ❌ %-10s not found\n" "$$cmd"; \
			fail=1; \
		fi; \
	done; \
	if [ $$fail -eq 1 ]; then echo "\nInstall missing prerequisites and retry."; exit 1; fi
	@echo "All prerequisites found."

init: check-prereqs ## One-time setup: install deps, configure env, start infra, build
	@echo ""
	@echo "=== Initializing Race Condition ==="
	@echo ""
	@if [ ! -f .env ]; then \
		echo "📋 Creating .env from .env.example..."; \
		cp .env.example .env; \
		echo "   Edit .env to set your GOOGLE_CLOUD_PROJECT and other config."; \
	else \
		echo "📋 .env already exists, skipping."; \
	fi
	@echo ""
	@echo "📦 Installing Python dependencies..."
	uv sync
	@echo ""
	@echo "📦 Installing and building web UIs..."
	cd web/frontend && npm install
	@for dir in web/admin-dash web/tester; do \
		if [ -f "$$dir/package.json" ]; then \
			echo "   Building $$dir..."; \
			(cd $$dir && npm install && npm run build) || exit 1; \
		fi; \
	done
	@echo ""
	@echo "🐳 Starting infrastructure (Redis, Pub/Sub, Postgres)..."
	docker compose up -d
	@echo ""
	@echo "🔨 Building Go services..."
	$(MAKE) build
	@echo ""
	@echo "=== Initialization Complete ==="
	@echo ""
	@# Port 9119 = Las Vegas zipcode 89119, home of Michelob Ultra Arena
	@# where Google Cloud Next 2026 was held. 🎰
	@echo "Next: run 'make start' to start all services."
