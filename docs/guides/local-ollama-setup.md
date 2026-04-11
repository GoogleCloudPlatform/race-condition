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
python agents/npc/runner/agent.py

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

When `RUNNER_MODEL` starts with `ollama_chat/`, the ADK routes requests through
its `LiteLlm` backend instead of the Gemini API:

```
LlmAgent(model="ollama_chat/gemma4:e2b")
  -> ADK LLMRegistry matches r"ollama_chat/.*"
  -> LiteLlm class
  -> litellm.acompletion()
  -> Ollama HTTP API (localhost:11434)
```

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

| Variable | Default | Description |
|---|---|---|
| `RUNNER_MODEL` | `gemini-3.1-flash-lite-preview` | Model string for the LLM runner |
| `RUNNER_PORT` | `8207` | HTTP port for the runner agent |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | Controls the `google-genai` SDK only. The `LiteLlm` backend used by Ollama models bypasses this SDK entirely, so the variable has no effect on the Ollama code path. You can leave it set. |

## See Also

- [GKE vLLM Setup](gke-vllm-setup.md) -- running Gemma 4 on GKE with L4 GPUs
  via vLLM (for production-like self-hosted inference)
