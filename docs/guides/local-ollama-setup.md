# Running the NPC Runner with Ollama (Local LLM)

This guide explains how to run the LLM-powered NPC runner agent using a local
Gemma 4 model via [Ollama](https://ollama.com), eliminating the need for GCP
credentials or Vertex AI access.

## Prerequisites

- **Ollama** installed and running ([ollama.com/download](https://ollama.com/download))
- **Python 3.13+** with `uv` (already required by the project)
- **litellm** (already included in project dependencies via `google-adk`)

## Quick Start

### 1. Install and start Ollama

```bash
# macOS (download from ollama.com or use Homebrew)
brew install ollama
ollama serve   # Start the daemon (or open Ollama.app)
```

### 2. Pull a Gemma 4 model

```bash
# Smallest model -- 7.2 GB, good for development/testing
ollama pull gemma4:e2b

# Verify it's available
ollama list
```

### 3. Configure the runner

Add or uncomment in your `.env`:

```bash
RUNNER_MODEL=ollama_chat/gemma4:e2b
```

Or export directly:

```bash
export RUNNER_MODEL=ollama_chat/gemma4:e2b
```

### 4. Run the runner agent

```bash
# Standalone (outside the full simulation)
python agents/runner/agent.py

# Or within the full simulation via Honcho
uv run start
```

## Available Gemma 4 Models

| Model | Ollama ID | Size | Context | Recommended For |
|---|---|---|---|---|
| **E2B** | `gemma4:e2b` | 7.2 GB | 128K | Development, quick iteration |
| **E4B** | `gemma4:e4b` | 9.6 GB | 128K | Better quality, still fast |
| **26B MoE** | `gemma4:26b` | 18 GB | 256K | High quality (3.8B active params) |
| **31B Dense** | `gemma4:31b` | 20 GB | 256K | Best quality, needs GPU/RAM |

Use the `ollama_chat/` prefix for all models:

```bash
RUNNER_MODEL=ollama_chat/gemma4:e2b    # Smallest
RUNNER_MODEL=ollama_chat/gemma4:e4b    # Balanced
RUNNER_MODEL=ollama_chat/gemma4:26b    # High quality
```

## How It Works

### Code Path

`agents/runner/agent.py` dispatches the model wrapper based on a prefix check
against the `RUNNER_MODEL` environment variable. Gemini strings go through the
project's `resilient_model()` (Vertex AI with retry); everything else goes
through ADK's `LiteLlm` backend, which delegates to `litellm`:

```python
# agents/runner/agent.py
_is_gemini = RUNNER_MODEL.startswith("gemini")
...
LlmAgent(
    model=resilient_model(RUNNER_MODEL) if _is_gemini else LiteLlm(model=RUNNER_MODEL),
    ...
)
```

So for `RUNNER_MODEL=ollama_chat/gemma4:e2b` the call chain is:

```
LlmAgent(model=LiteLlm(model="ollama_chat/gemma4:e2b"))
  -> litellm.acompletion(model="ollama_chat/...")
  -> Ollama HTTP API (localhost:11434)
```

> Without the `_is_gemini` branch, `resilient_model()` would unconditionally
> wrap the string in `GlobalGemini` and Vertex would 400 with
> `Invalid Endpoint name: projects/.../publishers/ollama_chat/models/...`.
> See the regression tests in `agents/runner/tests/test_agent.py` --
> `test_ollama_model_uses_litellm_not_global_gemini` and
> `test_gemini_model_still_uses_global_gemini`.

### What Changes

| Feature | Gemini (default) | Ollama |
|---|---|---|
| **Function calling** | Native API | Native Gemma 4 FC via litellm |
| **ThinkingConfig** | Suppressed (budget=0) | Omitted (not supported by litellm) |
| **Context caching** | Active (saves cost) | Skipped (not available) |
| **Authentication** | GCP credentials | None needed |
| **Latency** | ~50-100ms | ~350-700ms (local inference) |

### What Stays the Same

- All 7 runner tools (`accelerate`, `brake`, `get_vitals`, `process_tick`,
  `deplete_water`, `rehydrate`, `validate_and_emit_a2ui`)
- `include_contents="none"` (ADK-level, backend-agnostic)
- `static_instruction` (converted to system message)
- Tool state management via `tool_context.state`
- Session service selection (InMemory locally, VertexAI in cloud)

## Behavioral Differences

### Thinking output

Gemma 4 emits chain-of-thought reasoning before each response. These appear as
`thought:true` parts in the event stream. Because the runner uses
`include_contents="none"`, thinking tokens do not accumulate in session history.

### Tool call patterns

Gemma 4 E2B may call tools more aggressively than Gemini (e.g. two `accelerate`
calls per turn instead of one). The runner instruction allows "one or two tools
per message" so this is within spec.

## Concurrency Tuning (REQUIRED for usable Demo 5b throughput)

Out of the box, Ollama serializes inference requests per model with
`OLLAMA_NUM_PARALLEL=1`. With 10 LLM runners hitting `gemma4:e2b`
simultaneously, every tick takes ~10x longer than necessary. The default
`KEEP_ALIVE` of 5 minutes also causes the model to unload between bursts of
runner activity, adding repeated load/unload cost.

The following settings make Ollama practical for multi-runner Demo 5b runs:

| Variable | Recommended | Why |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `10` | Match the LLM runner cap (`MAX_RUNNERS_LLM`). One inference slot per runner. |
| `OLLAMA_MAX_QUEUE` | `512` | Buffers backed-up requests instead of dropping them. |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keeps `gemma4:e2b` resident between tick bursts. Eliminates load/unload overhead. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Apple-Silicon-safe. Faster + lower memory per slot. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Frees VRAM for parallel slots of the one model we use. |

### Apply the settings (macOS, Ollama.app)

Ollama.app reads env vars from the user launchd context, so set them with
`launchctl setenv` and restart the app:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 10
launchctl setenv OLLAMA_MAX_QUEUE 512
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 1

# Quit and relaunch Ollama (force-restart if a model is loaded):
pkill -x Ollama; pkill -f "ollama serve"; pkill -f "ollama runner"
sleep 3
open -a Ollama
```

To make these settings persist across reboots, add the same `launchctl
setenv` lines to a launch agent (e.g. `~/Library/LaunchAgents/`).

### Verify

After restart, trigger a small request to load the model, then inspect:

```bash
curl -s http://localhost:11434/api/chat \
  -d '{"model":"gemma4:e2b","stream":false,"messages":[{"role":"user","content":"hi"}],"options":{"num_predict":1}}' \
  >/dev/null
ollama ps
# UNTIL column should show ~30 minutes from now (was ~5 minutes by default).
# SIZE will be larger than baseline -- the extra is parallel-slot KV cache.
```

You can also inspect the live env in the running `ollama serve` process:

```bash
ps -E -p "$(pgrep -f 'ollama serve')" | tr ' ' '\n' | grep '^OLLAMA_'
```

### Memory math

`gemma4:e2b` base weights are ~8 GB on GPU. Each parallel slot adds KV cache
(~300 MB at the default 32k context). With `NUM_PARALLEL=10`:
~8 GB + 10 × ~300 MB ≈ ~11 GB unified memory. Comfortable on 16 GB Macs and
above. If memory is tight, reduce `NUM_PARALLEL` to 5 or use `gemma4:e2b`'s
context options to pin a smaller `num_ctx` per request (a single tick prompt
+ tool schema is well under 2k tokens).

### Linux / standalone `ollama serve`

If you run `ollama serve` directly (no Ollama.app supervisor), set the vars
inline:

```bash
OLLAMA_NUM_PARALLEL=10 \
OLLAMA_MAX_QUEUE=512 \
OLLAMA_KEEP_ALIVE=30m \
OLLAMA_FLASH_ATTENTION=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
ollama serve
```

## Troubleshooting

### "Model not found"

```
ValueError: Model ollama_chat/gemma4:e2b not found.
```

Ensure `litellm` is installed. It is included in the project dependencies, but
if you see this error, check:

```bash
.venv/bin/python -c "import litellm; print('OK')"
```

### Ollama not responding

```
Connection refused / timeout
```

Ensure Ollama is running:

```bash
ollama serve      # Start the daemon
ollama list       # Verify models are available
curl http://localhost:11434/api/tags  # Check API
```

### Empty responses

If the model returns empty text content, try a different model size. The E2B
model (2.3B effective params) may produce terse responses for complex prompts:

```bash
RUNNER_MODEL=ollama_chat/gemma4:e4b   # 4.5B effective params
```

### Ollama version too old

Gemma 4 requires Ollama 0.14+ (approximately). If `ollama pull gemma4:e2b`
fails with a 412 error, update Ollama from
[ollama.com/download](https://ollama.com/download).

## Environment Variable Reference

### Runner-side (read by the agent process)

| Variable | Default | Description |
|---|---|---|
| `RUNNER_MODEL` | `gemini-3.1-flash-lite-preview` | Model string for the LLM runner |
| `RUNNER_PORT` | `8207` | HTTP port for the runner agent |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | Controls the `google-genai` SDK only. The `LiteLlm` backend used by Ollama models bypasses this SDK entirely, so the variable has no effect on the Ollama code path. You can leave it set. |

### Ollama-side (read by `ollama serve`)

See [Concurrency Tuning](#concurrency-tuning-required-for-usable-demo-5b-throughput)
for context and apply commands.

| Variable | Recommended | Default | Description |
|---|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `10` | 1 (or auto) | Concurrent inference slots per model. |
| `OLLAMA_MAX_QUEUE` | `512` | 512 | Max queued requests before rejection. |
| `OLLAMA_KEEP_ALIVE` | `30m` | `5m` | How long the model stays in memory after last request. |
| `OLLAMA_FLASH_ATTENTION` | `1` | `0` | Enable flash attention (faster + lower memory). |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | (auto) | Cap concurrently-loaded models. Frees VRAM for parallel slots. |

## See Also

- [GKE vLLM Setup](gke-vllm-setup.md) -- running Gemma 4 on GKE with L4 GPUs
  via vLLM (for production-like self-hosted inference)
