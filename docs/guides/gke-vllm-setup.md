# GKE vLLM Setup Guide

Run the runner agent against Gemma 4 served by vLLM on GKE with L4 GPUs.

## Prerequisites

- `gcloud` CLI authenticated with `n26-devkey-simulation-dev` project access
- `kubectl` installed
- Access to the `model-serving-cluster` GKE cluster

## Architecture

```
Local Machine                          GKE (model-serving-cluster)
+-----------------+   kubectl          +--------------------------+
| Runner Agent    |   port-forward     | gpu-l4 node pool         |
| test script     |<------8080-------->| vLLM Pod (gemma-4-E4B-it)|
+-----------------+                    | GCS FUSE -> model weights|
                                       +--------------------------+
```

The vLLM server exposes an OpenAI-compatible API on port 8000. For local
testing, `kubectl port-forward` bridges your machine to the cluster.

## Quick Start

### 1. Get cluster credentials

```bash
gcloud container clusters get-credentials model-serving-cluster \
  --region=us-central1 --project=n26-devkey-simulation-dev
```

### 2. Verify vLLM is running

```bash
kubectl get pods -l app=vllm-server
# Should show 1/2 Running (2 containers: vllm + gcsfuse sidecar)
```

### 3. Start port-forward

```bash
kubectl port-forward svc/vllm-service 8080:8000
```

### 4. Test inference

In another terminal:

```bash
# Quick health check
curl http://localhost:8080/health

# List models
curl http://localhost:8080/v1/models

# Chat completion
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-E4B-it",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

### 5. Run the test script

```bash
python scripts/e2e/test_vllm_runner.py
```

This validates health, model listing, chat completions, and tool calling.

### 6. Run the runner agent against vLLM

```bash
RUNNER_MODEL=openai/gemma-4-E4B-it \
VLLM_API_URL=http://localhost:8080/v1 \
  python -m agents.npc.runner.agent
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `RUNNER_MODEL` | Model identifier with litellm prefix | `openai/gemma-4-E4B-it` |
| `VLLM_API_URL` | vLLM server base URL | `http://localhost:8080/v1` |

When `VLLM_API_URL` is set, the runner agent automatically configures
`OPENAI_API_BASE` and `OPENAI_API_KEY` for litellm routing.

## Model Backends

The runner agent supports three backends:

| Backend | RUNNER_MODEL | Notes |
|---------|-------------|-------|
| Gemini (default) | `gemini-3.1-flash-lite-preview` | Vertex AI, production |
| Ollama (local) | `ollama_chat/gemma4:e2b` | Local inference, dev only |
| vLLM (GKE) | `openai/gemma-4-E4B-it` | Self-hosted on GKE with L4 GPUs |

## Infrastructure

The vLLM infrastructure is managed in the `code-infra` repository:

- **Terraform**: `code-infra/projects/dev/gke.tf` -- GKE cluster, node pools,
  IAM, GCS bucket
- **Kustomize**: `code-infra/k8s/vllm/` -- vLLM deployment, service, model
  download job

### Deploying vLLM

```bash
# From the code-infra repo
kubectl apply -k k8s/vllm/overlays/dev/
kubectl rollout status deployment/vllm-server --timeout=300s
```

### Downloading a new model

Update `k8s/vllm/jobs/model-download.yaml` with the new model ID, then:

```bash
kubectl apply -f k8s/vllm/jobs/model-download.yaml
kubectl wait --for=condition=complete job/model-downloader-<name> --timeout=600s
```

## Troubleshooting

### Port-forward connection refused

```
FAIL: Cannot connect. Is port-forward running?
```

Ensure `kubectl port-forward svc/vllm-service 8080:8000` is running in another
terminal. If the pod isn't ready, wait for the readiness probe to pass:

```bash
kubectl get pods -l app=vllm-server -w
```

### Pod stuck in PodInitializing

The GCS FUSE sidecar needs to mount the model bucket. First-time cold start
can take 3-5 minutes for model weight caching.

### Model not found

If `/v1/models` returns an empty list, check the vLLM container logs:

```bash
kubectl logs deployment/vllm-server -c vllm --tail=50
```

Common causes: model path mismatch in args, missing `config.json` in GCS.

### GPU scheduling issues

If the pod is Pending, check for GPU availability:

```bash
kubectl describe pod -l app=vllm-server | grep -A5 "Events:"
kubectl get nodes -l cloud.google.com/gke-accelerator=nvidia-l4
```

## See Also

- [Local Ollama Setup](local-ollama-setup.md) -- running Gemma 4 locally
- [Design Document](../plans/2026-04-06-gemma4-vllm-gke-design.md) -- full
  architecture and design decisions
