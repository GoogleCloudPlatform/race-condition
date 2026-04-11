# Runner agent (LLM-powered)

An LLM-powered marathon runner NPC. Each instance represents one runner in
the simulation, receiving tick events from the simulator, making pacing and
hydration decisions via a language model, and advancing its own physics state.
Hundreds run concurrently.

## How it works

Each tick, the runner agent:

1. Receives a tick message from the simulator (elapsed time, tick number,
   collector buffer key)
2. The LLM reads the tick and decides: accelerate or brake? how hard?
   rehydrate?
3. Tools execute the decisions: adjust velocity, update hydration
4. `process_tick` runs the deterministic physics engine: compute distance,
   deplete hydration, apply wall/fatigue effects, detect finish or collapse
5. Results are written directly to a Redis collector buffer for the simulator
   to aggregate

### What the LLM controls

- **Pacing intensity**: the `intensity` parameter (0.0-1.0) for `accelerate`
  or `brake`
- **Hydration timing**: when to `rehydrate` at a station (guidelines in the
  prompt, but the LLM interprets them)
- **Inner thought**: a 5-word-max internal monologue per tick -- "random
  cravings, regrets, weird observations, bargaining with their legs." Every
  thought must be unique across ticks.

### What is deterministic (no LLM)

- **Runner profile**: velocity, wall chance, hydration efficiency, crowd
  responsiveness, wave assignment -- all generated from `sha256(session_id)`,
  fully reproducible
- **Physics**: distance traveled, hydration depletion rates, wall effect,
  fatigue degradation, finish detection -- computed from constants and state
- **Auto-hydration at stations**: checked every ~1.86 miles using per-station
  seeded RNG
- **Exhaustion/collapse**: triggered by hydration thresholds (< 30% exhausted,
  < 10% collapsed)

The LLM provides strategic pacing and creative personality. The physics engine
enforces realistic constraints regardless of what the LLM decides.

## Runner initialization

On the first tick, `initialize_runner()` generates a complete profile from the
session ID. The profile is deterministic -- the same session ID always produces
the same runner.

Key parameters drawn from seeded distributions:

| Parameter | Distribution | Range |
|:----------|:-------------|:------|
| Target finish time | Log-normal (mu=5.27, sigma=0.25) | ~120-360 minutes |
| Will hit wall | Bernoulli (40%) | true/false |
| Wall mile marker | Gaussian (18.6, sigma=1.0) | ~16-21 miles |
| Wall severity | Beta (2, 5) | 0.0-1.0 |
| Hydration efficiency | Ability-scaled | Lower = more efficient |
| Crowd responsiveness | Bernoulli (25%) | responsive/ignores |

Fast runners (low target time) get high velocity, efficient hydration, and
earlier wave starts. Back-of-pack runners get lower velocity but more
sustainable hydration.

## Tools

| Tool | Module | Purpose |
|:-----|:-------|:--------|
| `accelerate` | `running.py` | Increase velocity by intensity * scale factor |
| `brake` | `running.py` | Decrease velocity by intensity * scale factor |
| `get_vitals` | `running.py` | Read current state (velocity, distance, water, status) |
| `process_tick` | `running.py` | Advance physics, write results to Redis buffer |
| `deplete_water` | `hydration.py` | Manually reduce hydration |
| `rehydrate` | `hydration.py` | Restore hydration at a station |
| `validate_and_emit_a2ui` | (shared skill) | Emit A2UI components |

## Wave start system

`compute_wave()` assigns runners to starting corrals based on ability (faster
runners start first), mimicking real marathon corral distributions. On tick 1,
runners in later waves get a `gateway_delay_seconds` field (2 seconds per wave)
so the frontend visualizes staggered starts.

## Model backends

The agent supports three model backends, selected via environment variables:

| Backend | Model | Use case |
|:--------|:------|:---------|
| Gemini (default) | `gemini-3.1-flash-lite-preview` | Production, Vertex AI |
| Ollama | `gemma4:e2b` via litellm | Local development |
| vLLM | `gemma-4-E4B-it` via litellm | GKE self-hosted |

The agent name is configurable via `AGENT_NAME` (defaults to `"runner"`, set
to `"runner_gke"` for GKE deployments).

## Performance design

The agent is optimized for hundreds of concurrent instances:

| Technique | Why it matters |
|:----------|:---------------|
| `include_contents="none"` | No conversation history between ticks. Each tick is a fresh LLM call with only the system prompt. Without this, context grows linearly and hundreds of runners exhaust memory. |
| `static_instruction` | Enables Vertex AI context caching (no template variable substitution needed). |
| Direct Redis writes | `process_tick` writes results to a Redis LIST via `RPUSH`, bypassing PubSub contention at high runner counts. |
| Telemetry suppression | Per-tick LLM chatter (`run_start`, `model_start`, etc.) is suppressed from dashboards. Only collector buffer results reach the frontend. |

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` / `RUNNER_PORT` | `8207` | HTTP listen port |
| `AGENT_NAME` | `runner` | Agent name (use `runner_gke` for GKE) |
| `RUNNER_MODEL` | `gemini-3.1-flash-lite-preview` | Model identifier (e.g., `ollama_chat/gemma4:e2b` for Ollama) |
| `VLLM_API_URL` | -- | vLLM endpoint (sets `OPENAI_API_BASE` for litellm) |

## File layout

```
agents/runner/
├── agent.py             # LlmAgent, model backend selection, A2A deployment
├── constants.py         # Shared physics constants (also used by runner_autopilot)
├── initialization.py    # Deterministic runner profile generation
├── running.py           # accelerate, brake, get_vitals, process_tick
├── hydration.py         # deplete_water, rehydrate
├── waves.py             # Wave/corral assignment
├── skills/
│   ├── running/         # Skill wrapper for running tools
│   └── hydration/       # Skill wrapper for hydration tools
└── tests/               # 6 test files
```

## Further reading

- The deterministic variant ([agents/runner_autopilot/](../runner_autopilot/))
  uses callbacks instead of an LLM for the same physics engine
- The simulator ([agents/simulator/](../simulator/)) spawns and drives
  runner agents
- The shared constants in `constants.py` are the single source of truth for
  both runner variants
