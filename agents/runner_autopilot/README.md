# Runner autopilot (deterministic)

A deterministic marathon runner that uses the same physics engine as the
[LLM-powered runner](../runner/) but replaces all LLM calls with a
`before_model_callback`. Zero API cost per tick, fully reproducible per
session ID.

## How it avoids the LLM

ADK calls `before_model_callback` before every model invocation. If the
callback returns an `LlmResponse`, the model call is skipped entirely. The
autopilot callback **always** returns an `LlmResponse` -- there is no code
path that returns `None`. The model is never called.

As defense in depth, `generate_content_config` is set to `temperature=0.0`
and `max_output_tokens=1`, so even if the callback somehow failed, the LLM
would produce minimal output.

## Event dispatch

The callback operates as a two-phase state machine per event:

**Phase 1 (DECIDE)**: parse the incoming message, classify the event type,
dispatch to a handler, return either a `FunctionCall` or text response.

**Phase 2 (SUMMARIZE)**: after ADK executes the tool and appends a
`function_response`, the callback is called again. It detects the response
and returns a text summary.

Handlers for each event type:

| Event | Handler | Action |
|:------|:--------|:-------|
| `START_GUN` | `handle_start_gun` | Return text acknowledgment. Runner init is deferred to tick 0. |
| `TICK` | `handle_tick` | On first tick: call `initialize_runner()` to generate profile. Then return `FunctionCall("process_tick", ...)`. |
| `CROWD_BOOST` | `handle_crowd_boost` | Return `FunctionCall("accelerate", {intensity})`. |
| `HYDRATION_STATION` | `handle_hydration_station` | Probabilistic: water <= 40% always rehydrate, 41-60% = 50% chance, > 60% = 30% chance. |
| `DISTANCE_UPDATE` | `handle_distance_update` | No-op (returns text). `process_tick` handles hydration depletion; calling `deplete_water` here would cause double depletion. |

## How pacing works without an LLM

The LLM runner calls `accelerate`/`brake` each tick with a chosen intensity.
The autopilot takes a simpler approach:

1. `initialize_runner()` sets a velocity from the seeded log-normal
   distribution (same code as the LLM runner)
2. That velocity persists for the entire race -- no per-tick adjustments
3. Speed degradation comes entirely from the physics engine: hydration factor,
   wall effect, and natural fatigue are applied inside `process_tick`
4. The only external velocity change is `crowd_boost`, which 75% of runners
   ignore (seeded `crowd_responsiveness = 0.0`)

This produces realistic race dynamics without any LLM inference.

## Code reuse

The autopilot contains zero physics logic. It inherits the entire base runner
agent via `get_agent()` and overrides three properties:

```python
agent = get_base_agent()
agent.name = "runner_autopilot"
agent.before_model_callback = autopilot_callback
agent.before_agent_callback = None  # init handled in handle_tick
```

All 7 tools (`accelerate`, `brake`, `get_vitals`, `process_tick`,
`deplete_water`, `rehydrate`, `validate_and_emit_a2ui`) are inherited
unchanged. Tests verify the tools are identity-same objects as the base
runner's implementations.

The only unique code is `autopilot.py` (279 lines): event dispatch, 5
handlers, phase detection, and summary building.

## Differences from the LLM runner

| Aspect | LLM runner | Autopilot |
|:-------|:-----------|:----------|
| Decision maker | Gemini/Ollama/vLLM | Callback dispatch table |
| LLM calls per tick | 1 | 0 |
| Per-tick pacing | LLM chooses accelerate/brake intensity | Initial velocity persists |
| Inner thoughts | LLM generates 5-word monologue | None |
| Cost per runner | LLM API cost per tick | Zero |
| Determinism | Non-deterministic (LLM varies) | Deterministic per session ID |
| Port | 8207 | 8210 |

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` / `RUNNER_AUTOPILOT_PORT` | `8210` | HTTP listen port |

## File layout

```
agents/runner_autopilot/
├── agent.py           # get_base_agent() + callback override + A2A deployment
├── autopilot.py       # Event dispatch, 5 handlers, phase detection (279 lines)
└── tests/
    ├── test_agent.py         # Wiring, tool identity, callback presence
    ├── test_autopilot.py     # Handler logic, phase detection, dispatch
    └── test_integration.py   # Full ADK InMemoryRunner pipeline tests
```

## Further reading

- The LLM-powered runner ([agents/runner/](../runner/)) shares all physics
  code and tools
- The shared constants ([agents/runner/constants.py](../runner/constants.py))
  are the single source of truth for simulation parameters
- The simulator ([agents/simulator/](../simulator/)) spawns `runner_autopilot`
  as the default runner type
