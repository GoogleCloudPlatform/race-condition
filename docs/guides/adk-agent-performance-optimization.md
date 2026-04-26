# ADK Agent Performance Optimization Guide

A project-agnostic guide to optimizing Google ADK agents for latency,
throughput, cost, and reliability. Written against ADK v1.30.0 and
google-genai v1.64.0.

## How to read this guide

Every technique is scored on three axes:

| Axis       | Scale | Meaning                                                |
| :--------- | :---- | :----------------------------------------------------- |
| **Impact** | 1–5   | How much performance improvement you can expect        |
| **Effort** | 1–5   | Implementation complexity (1 = trivial, 5 = major)     |
| **Risk**   | 1–5   | Chance of introducing regressions or behavioral change |

Start with high-impact, low-effort items. Section 21 sorts everything by ROI
(impact ÷ effort).

---

## 1. Model Selection & Configuration

**Impact: 5 · Effort: 1 · Risk: 2**

The single most impactful decision is choosing the right model for each agent's
job.

### Model tiers

| Tier  | Example Model                   | Speed   | Cost | Quality  | Best For                    |
| :---- | :------------------------------ | :------ | :--- | :------- | :-------------------------- |
| Pro   | `gemini-3.1-pro-preview`        | Slow    | High | Best     | Complex reasoning, planning |
| Flash | `gemini-3-flash-preview`        | Fast    | Med  | Good     | General-purpose agents      |
| Lite  | `gemini-3.1-flash-lite-preview` | Fastest | Low  | Adequate | High-volume NPCs, routing   |

### Temperature guidelines

| Value   | Behavior      | Use Case                              |
| :------ | :------------ | :------------------------------------ |
| 0.0     | Deterministic | Classification, routing, tool calling |
| 0.1–0.3 | Focused       | Planning, structured output           |
| 0.4–0.7 | Balanced      | General conversation                  |
| 0.8–1.0 | Creative      | Storytelling, brainstorming           |

### Additional `GenerateContentConfig` Levers

```python
from google.genai import types

config = types.GenerateContentConfig(
    temperature=0.2,
    top_p=0.95,             # Nucleus sampling threshold
    top_k=40,               # Limits token candidates per step
    max_output_tokens=1024, # Hard cap on response length
    stop_sequences=["END"], # Early termination triggers
    seed=42,                # Reproducible outputs (for testing)
)
```

### Decision shortcut

If the agent does complex multi-step reasoning, use Pro at temp 0.1–0.3. For
general-purpose work, Flash at 0.2–0.5. For high-volume NPCs (>50 concurrent),
always Lite at 0.0–0.3 — the cost difference dominates everything else.

---

## 2. Thinking Budget Control

**Impact: 4 · Effort: 1 · Risk: 2**

Gemini models that support "thinking" (internal chain-of-thought) consume
additional tokens for reasoning before producing a response. You can control
this with `ThinkingConfig`.

### Configuration

```python
from google.genai import types

# Disable thinking entirely — fastest responses
types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)

# Automatic thinking — model decides how much to think
types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=-1),
)

# Fixed budget — 1024 thinking tokens max
types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=1024),
)
```

### When to Use Each Setting

| Setting     | Use When                                        |
| :---------- | :---------------------------------------------- |
| `budget=0`  | Reactive agents, routing, simple tool calls     |
| `budget=-1` | Default — let the model decide                  |
| `budget=N`  | You need reasoning but want to cap cost/latency |

> [!IMPORTANT] Disabling thinking on agents that need multi-step reasoning
> **will degrade output quality**. Always validate with your evaluation suite
> before shipping.

---

## 3. Context Caching (Explicit)

**Impact: 5 · Effort: 2 · Risk: 1**

Gemini's Context Caching stores system instructions, tools, and early
conversation turns server-side. Subsequent requests reuse the cache, cutting
input token costs by **50–75%** and reducing latency.

### Configuration

```python
from google.adk.apps import App
from google.adk.agents.context_cache_config import ContextCacheConfig

app = App(
    name="my_agent",
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(
        cache_intervals=10,   # Reuse cache for N invocations before refresh
        ttl_seconds=1800,     # 30-minute time-to-live
        min_tokens=4096,      # Only cache if request exceeds this threshold
    ),
)
```

### How it works

1. ADK's `ContextCacheRequestProcessor` checks session events for existing cache
   metadata.
2. `GeminiContextCacheManager` generates a fingerprint (hash of system
   instruction + tools + first N contents).
3. If the fingerprint matches an existing valid cache, it's reused.
4. Cached content is removed from the request payload, reducing billed tokens.

### Cost model

- Cached input tokens are billed at **~0.25×** the normal input rate.
- Cache storage incurs a small per-hour fee.
- Break-even point: typically 3–5 requests with the same cached prefix.

### Best practices

- Pair with `static_instruction` (see §4) for maximum cache hit rate.
- Set `min_tokens` high enough to avoid caching small requests where overhead
  exceeds savings.
- Monitor hit rates with `CachePerformanceAnalyzer` (see §19).

---

## 4. Static vs Dynamic Instructions

**Impact: 4 · Effort: 2 · Risk: 1**

`LlmAgent` supports two instruction fields that control prompt placement:

| Field                | Placement                          | Variable substitution | Cacheable                               |
| :------------------- | :--------------------------------- | :-------------------- | :-------------------------------------- |
| `static_instruction` | System instruction (first)         | ❌ None               | ✅ Yes                                  |
| `instruction`        | System instruction OR user content | ✅ `{var}` syntax     | ⚠️ Only if static_instruction is absent |

### The key insight

When `static_instruction` is set, `instruction` moves to **user content**. This
means the stable prefix (system instruction) never changes, making it an ideal
candidate for context caching.

### Pattern

```python
STATIC_RULES = """
You are a financial advisor agent. You must always:
- Comply with SEC regulations
- Never provide specific stock recommendations
- Always disclose that you are an AI
... (large static knowledge base that never changes) ...
"""

DYNAMIC_PART = """
The user's portfolio value is ${portfolio_value}.
Their risk tolerance is {risk_level}.
"""

agent = LlmAgent(
    name="advisor",
    static_instruction=STATIC_RULES,
    instruction=DYNAMIC_PART,       # Goes to user content
    ...
)
```

### When to Split

| Content Type                    | Where It Goes        |
| :------------------------------ | :------------------- |
| Persona, rules, compliance text | `static_instruction` |
| Reference documents, schemas    | `static_instruction` |
| Session-specific variables      | `instruction`        |
| User-dependent context          | `instruction`        |

---

## 5. Parallel Tool Execution

**Impact: 4 · Effort: 1 · Risk: 1**

When the LLM returns **multiple function calls in a single response**, ADK
automatically executes them in parallel via `asyncio.gather()`.

### Requirements

1. **Tools must be `async def`** — synchronous tools block the event loop and
   prevent true concurrency.
2. **Tools must be independent** — no tool should depend on another tool's
   output within the same batch.
3. **Tools must be thread-safe** — avoid shared mutable state.

### Under the hood

```python
# google/adk/flows/llm_flows/functions.py
tasks = [asyncio.create_task(_execute_single_function_call_async(...))
         for function_call in filtered_calls]
function_response_events = await asyncio.gather(*tasks)
```

### Encouraging parallel calls

The LLM decides whether to emit multiple function calls. You can encourage this
behavior through prompt engineering:

```
When you need information from multiple independent sources,
call all relevant tools simultaneously in a single response.
```

---

## 6. Tool Thread Pool Offloading

**Impact: 3 · Effort: 1 · Risk: 1**

For tools with blocking I/O or for Live API mode, ADK can run tools in a
background `ThreadPoolExecutor` to keep the event loop responsive.

### Configuration

```python
from google.adk.agents.run_config import RunConfig, ToolThreadPoolConfig

run_config = RunConfig(
    tool_thread_pool_config=ToolThreadPoolConfig(max_workers=8),
)
```

### When it helps

| Scenario                       | Benefits?                        |
| :----------------------------- | :------------------------------- |
| Blocking network calls         | ✅ Yes — GIL released during I/O |
| File I/O, database queries     | ✅ Yes — GIL released during I/O |
| C extensions (numpy, hashlib)  | ✅ Yes — GIL released            |
| Pure Python loops/calculations | ❌ No — GIL held                 |
| Already-async tools            | ⚠️ Marginal — catches mistakes   |

---

## 7. Parallel Agent Execution

**Impact: 4 · Effort: 3 · Risk: 2**

ADK's `ParallelAgent` runs sub-agents concurrently using `asyncio.TaskGroup`,
each in an isolated branch context.

### Use cases

- **Best-of-N generation**: Multiple agents tackle the same problem; a parent
  selects the best output.
- **Fan-out/fan-in**: Divide a large task into independent sub-tasks.
- **Redundancy**: Run the same query against different models for reliability.

### Example

```python
from google.adk.agents import ParallelAgent, LlmAgent

analyzer_1 = LlmAgent(name="analyzer_fast", model="gemini-3-flash-preview", ...)
analyzer_2 = LlmAgent(name="analyzer_deep", model="gemini-3.1-pro-preview", ...)

parallel = ParallelAgent(
    name="multi_analyzer",
    sub_agents=[analyzer_1, analyzer_2],
)
```

### Limitations

- Sub-agents share no state — each gets an isolated branch.
- Live mode (`run_live`) is **not supported** for `ParallelAgent`.
- Results must be merged by a parent agent downstream.

---

## 8. Parallel A2A Orchestration

**Impact: 4 · Effort: 2 · Risk: 2**

For agents communicating over the A2A protocol (HTTP), orchestration calls can
be parallelized using `asyncio.gather()`.

### Pattern

```python
import asyncio

async def fan_out_to_agents(tool_context, messages: dict[str, str]):
    """Call multiple remote agents concurrently."""
    tasks = [
        call_agent(tool_context, agent_name, message)
        for agent_name, message in messages.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = {name: r for name, r in zip(messages.keys(), results)
                 if not isinstance(r, Exception)}
    failures = {name: str(r) for name, r in zip(messages.keys(), results)
                if isinstance(r, Exception)}
    return {"successes": successes, "failures": failures}
```

### Considerations

- **QPM limits**: Parallel calls multiply your effective API rate.
- **Connection pooling**: Ensure your HTTP client reuses connections.
- **Error isolation**: Use `return_exceptions=True` so one failure doesn't
  cancel all calls.
- **Timeouts**: Set per-call timeouts with `asyncio.wait_for()`.

---

## 9. Context Window Compression

**Impact: 3 · Effort: 1 · Risk: 2**

`RunConfig.context_window_compression` enables Gemini to automatically compress
the context when it approaches limits.

```python
from google.genai import types
from google.adk.agents.run_config import RunConfig

run_config = RunConfig(
    context_window_compression=types.ContextWindowCompressionConfig(),
)
```

### When to Use

- Long-running sessions that accumulate many events.
- Agents with large tool response histories.
- Any agent that risks hitting context window limits.

---

## 10. Event Compaction

**Impact: 3 · Effort: 2 · Risk: 2**

ADK's `CompactionRequestProcessor` prunes or summarizes old session events when
the conversation exceeds a token threshold. This is a **client-side**
optimization — events are compacted before being sent to the model.

### Difference from Context Caching

| Feature            | Context Caching       | Event Compaction     |
| :----------------- | :-------------------- | :------------------- |
| **What it caches** | System prompt + tools | Conversation history |
| **Where it runs**  | Gemini API server     | ADK client           |
| **Cost savings**   | Discounted token rate | Fewer tokens sent    |
| **Best for**       | Stable prefixes       | Long conversations   |

### When to Use

Use both together for maximum savings: cache the stable prefix, compact the
dynamic history.

---

## 11. Output Token Budgeting

**Impact: 3 · Effort: 1 · Risk: 1**

Set `max_output_tokens` in `GenerateContentConfig` to prevent the model from
generating excessively long responses.

```python
types.GenerateContentConfig(
    max_output_tokens=512,   # Concise responses
)
```

### Guidelines

| Agent Type         | Suggested Limit | Reasoning                         |
| :----------------- | :-------------- | :-------------------------------- |
| Tool-calling agent | 256–512         | Only needs to emit function calls |
| Conversational     | 1024–2048       | Balanced output                   |
| Report generator   | 4096+           | Needs space for detailed output   |
| Router/classifier  | 128             | Just needs a decision             |

> [!WARNING] Setting this too low will cause truncated outputs. Always test with
> your longest expected response.

---

## 12. LLM Call Guards

**Impact: 2 · Effort: 1 · Risk: 1**

`RunConfig.max_llm_calls` limits the total number of model calls per invocation,
preventing infinite tool-calling loops.

```python
from google.adk.agents.run_config import RunConfig

run_config = RunConfig(max_llm_calls=10)  # Default is 500
```

### Recommendations

| Agent Type             | Suggested Limit | Why                           |
| :--------------------- | :-------------- | :---------------------------- |
| Simple tool-call agent | 5–10            | Should resolve in 1–3 loops   |
| Complex planner        | 20–50           | May need multiple tool rounds |
| Orchestrator           | 50–100          | Manages many sub-agent calls  |

---

## 13. Content Inclusion Control

**Impact: 3 · Effort: 1 · Risk: 3**

`LlmAgent.include_contents` controls whether the model receives conversation
history.

```python
agent = LlmAgent(
    name="stateless_classifier",
    include_contents='none',   # No history, just current instruction + input
    ...
)
```

### Options

| Value     | Behavior                                     | Use Case                       |
| :-------- | :------------------------------------------- | :----------------------------- |
| `default` | Model receives relevant conversation history | Most agents                    |
| `none`    | Model receives no prior history              | Stateless classifiers, routers |

### When to Use `none`

- The agent doesn't need conversational context.
- You want maximum cache efficiency (fewer varying contents).
- The agent is called repeatedly with independent inputs.

---

## 14. Streaming Mode Selection

**Impact: 2 · Effort: 1 · Risk: 1**

Choose the streaming mode based on your delivery channel.

```python
from google.adk.agents.run_config import RunConfig, StreamingMode

run_config = RunConfig(streaming_mode=StreamingMode.SSE)
```

| Mode   | Time to First Byte | Throughput | Best For                     |
| :----- | :----------------- | :--------- | :--------------------------- |
| `NONE` | Higher             | Best       | Batch processing, CLI, tests |
| `SSE`  | Lowest             | Good       | Web UIs, chat interfaces     |
| `BIDI` | Lowest             | Variable   | Voice, real-time streams     |

---

## 15. Prompt Engineering for Efficiency

**Impact: 4 · Effort: 2 · Risk: 2**

Well-structured prompts reduce token usage and improve tool-calling accuracy.

### Principles

1. **Be concise** — every unnecessary word is a wasted token, on every single
   request.
2. **Use structured formats** — markdown headers, numbered lists, and tables
   parse more efficiently than prose paragraphs.
3. **Front-load critical information** — the model attends more strongly to
   earlier tokens.
4. **Specify output format explicitly** — "Respond with a JSON object
   containing..." prevents the model from adding verbose preambles.
5. **Eliminate redundancy** — if a tool's description already explains its
   purpose, don't repeat it in the instruction.

### Anti-Patterns

| Anti-Pattern                     | Fix                                      |
| :------------------------------- | :--------------------------------------- |
| "Please", "Thank you" in prompts | Remove — they waste tokens               |
| Repeating tool descriptions      | Reference the tool by name only          |
| Verbose examples in every call   | Move to `static_instruction` for caching |
| Unstructured instructions        | Use headers, numbered steps              |

### Token estimation rule of thumb

- 1 token ≈ 4 characters in English.
- 100 tokens ≈ 75 words.

Multiply your instruction token count by your call rate to estimate cost.
Don't trust any specific dollar number you read in a doc — pricing changes
frequently. Pull current per-token pricing from the [Vertex AI pricing
page](https://cloud.google.com/vertex-ai/generative-ai/pricing) when you need
a real number.

---

## 16. Automated Prompt Optimization (GEPA)

**Impact: 4 · Effort: 4 · Risk: 2**

ADK includes an Agent Optimizer for systematically improving prompts against
an evaluation dataset.

### Usage

```python
from google.adk.optimization.simple_prompt_optimizer import (
    SimplePromptOptimizer,
    SimplePromptOptimizerConfig,
)

config = SimplePromptOptimizerConfig(...)  # see google.adk.optimization
optimizer = SimplePromptOptimizer(config)
result = await optimizer.optimize(
    initial_agent=my_agent,
    sampler=my_evaluation_sampler,  # implements Sampler[UnstructuredSamplingResult]
)
optimized_agent = result.best.agent
```

The constructor requires a `SimplePromptOptimizerConfig` — calling
`SimplePromptOptimizer()` with no args raises `TypeError`. See
`google.adk.optimization` for config options.

---

## 17. Session Service Selection

**Impact: 3 · Effort: 1 · Risk: 1**

The session service stores agent state between invocations. Choose based on your
deployment environment.

| Backend                  | Concurrency  | Latency    | Persistence | Use Case                 |
| :----------------------- | :----------- | :--------- | :---------- | :----------------------- |
| `InMemorySessionService` | Excellent    | ~0 ms      | None        | Dev / Test               |
| `VertexAiSessionService` | Good         | ~50–200 ms | Cloud       | Production               |
| SQLite (ADK default)     | **Terrible** | Variable   | File        | **Never use under load** |

> [!CAUTION] SQLite's file-level locking causes `LOCKED` errors under concurrent
> access. **Never use SQLite** for any workload with more than one concurrent
> agent. Use `InMemorySessionService` for local development and
> `VertexAiSessionService` for production.

---

## 18. Python performance checklist

**Impact: 3 · Effort: 2 · Risk: 1**

ADK runs on Python's `asyncio`, and most agent perf issues are general Python
performance issues, not ADK-specific ones. The list below assumes you've
already read the canonical Python references on these topics; treat it as a
review checklist, not a tutorial.

- **Use `async def` for every tool.** A blocking `def` tool stalls the event
  loop and serializes everything else the agent is doing. If you absolutely
  must call a sync library, wrap it in `asyncio.to_thread`.
- **Parallelize independent calls with `asyncio.gather`.** Sequential `await`s
  on independent operations are the single most common performance bug.
- **Set timeouts on every external call.** `asyncio.wait_for(op, timeout=5.0)`.
  An agent silently hanging on a stuck HTTP call is worse than a clean error.
- **Share an `aiohttp.ClientSession`.** A new session per request creates a
  new TCP connection each time. Hold one module-level session with
  `aiohttp.TCPConnector(limit=100)` and reuse it.
- **Don't deep-copy tool arguments.** ADK already deep-copied them before
  invoking your tool. An extra `copy.deepcopy` is pure waste.
- **Return lean dicts from tools.** The LLM has to read everything you return.
  Return only the fields needed for the next reasoning step, not the whole
  underlying object.
- **Use `%`-formatted logging, not f-strings.** `logger.debug("count=%d",
  n)` skips formatting when debug is disabled. `logger.debug(f"count={n}")`
  always pays the format cost.
- **Yield the event loop inside CPU-bound loops.** `await asyncio.sleep(0)`
  every N iterations. Otherwise the runner can't service other coroutines.
- **`__slots__` on hot dataclasses, generators for large iterables,
  `functools.lru_cache` on pure expensive functions, `set` lookups for
  membership tests.** All standard Python advice; nothing ADK-specific.

For deeper coverage, see the [asyncio
documentation](https://docs.python.org/3/library/asyncio.html) and the
[aiohttp connection pooling
guide](https://docs.aiohttp.org/en/stable/client_advanced.html#connection-pooling).

---

## 19. Monitoring & Measurement

**Impact: 3 · Effort: 2 · Risk: 0**

You can't optimize what you don't measure.

### ADK Cache Performance Analyzer

```python
from google.adk.utils.cache_performance_analyzer import CachePerformanceAnalyzer

analyzer = CachePerformanceAnalyzer(session_service=session_service)
report = await analyzer.analyze_agent_cache_performance(
    session_id="...", user_id="...", app_name="my_app", agent_name="my_agent",
)
# report contains: cache_hit_ratio_percent, total_cached_tokens,
#                   cache_utilization_ratio_percent, etc.
```

### Key metrics to track

| Metric                       | Target     | How to Measure             |
| :--------------------------- | :--------- | :------------------------- |
| Cache hit ratio              | > 70%      | `CachePerformanceAnalyzer` |
| Avg input tokens per request | Decreasing | `event.usage_metadata`     |
| Response latency (p50 / p95) | < 2s / 5s  | OpenTelemetry traces       |
| LLM calls per invocation     | < 5        | `max_llm_calls` monitoring |
| Tool execution time          | < 500ms    | `trace_tool_call` spans    |
| Error rate                   | < 1%       | Exception logging          |

### OpenTelemetry Integration

ADK provides built-in tracing via `google.adk.telemetry.tracing`. Key spans:

- `execute_tool {tool_name}` — individual tool execution
- `execute_tool (merged)` — merged parallel tool execution
- LLM request/response spans — model call timing

---

## 20. Summary Table

All techniques ranked by **impact ÷ effort** (best return on investment first):

| #   | Technique                       | Impact | Effort | Risk | ROI Score |
| :-- | :------------------------------ | :----: | :----: | :--: | :-------: |
| 1   | Model Selection                 |   5    |   1    |  2   |    5.0    |
| 2   | Thinking Budget Control         |   4    |   1    |  2   |    4.0    |
| 3   | Parallel Tool Execution (async) |   4    |   1    |  1   |    4.0    |
| 4   | Output Token Budgeting          |   3    |   1    |  1   |    3.0    |
| 5   | Content Inclusion Control       |   3    |   1    |  3   |    3.0    |
| 6   | Session Service Selection       |   3    |   1    |  1   |    3.0    |
| 7   | Tool Thread Pool Offloading     |   3    |   1    |  1   |    3.0    |
| 8   | Context Window Compression      |   3    |   1    |  2   |    3.0    |
| 9   | Context Caching (Explicit)      |   5    |   2    |  1   |    2.5    |
| 10  | LLM Call Guards                 |   2    |   1    |  1   |    2.0    |
| 11  | Streaming Mode Selection        |   2    |   1    |  1   |    2.0    |
| 12  | Static vs Dynamic Instructions  |   4    |   2    |  1   |    2.0    |
| 13  | Prompt Engineering              |   4    |   2    |  2   |    2.0    |
| 14  | Parallel A2A Orchestration      |   4    |   2    |  2   |    2.0    |
| 15  | Python Performance Checklist    |   3    |   2    |  1   |    1.5    |
| 16  | Event Compaction                |   3    |   2    |  2   |    1.5    |
| 17  | Monitoring & Measurement        |   3    |   2    |  0   |    1.5    |
| 18  | Parallel Agent Execution        |   4    |   3    |  2   |    1.3    |
| 19  | Automated Prompt Optimization   |   4    |   4    |  2   |    1.0    |

> [!NOTE] **ROI Score** = Impact ÷ Effort. Higher is better. Start from the top.

---

## Quick-Start Checklist

For a new ADK agent project, apply these optimizations in order:

- [ ] Choose the right model tier for each agent role (§1)
- [ ] Set `thinking_budget` appropriately per agent (§2)
- [ ] Set `max_output_tokens` on every agent (§11)
- [ ] Set `max_llm_calls` guard on every `RunConfig` (§12)
- [ ] Make all tool functions `async def` (§5, §18)

  (See §18 for the full Python performance checklist — async, timeouts,
  shared HTTP sessions, lean tool returns, lazy logging.)
- [ ] Configure `ContextCacheConfig` on the `App` (§3)
- [ ] Split stable content into `static_instruction` (§4)
- [ ] Use `include_contents='none'` for stateless agents (§13)
- [ ] Choose the correct `StreamingMode` per delivery channel (§14)
- [ ] Set up `CachePerformanceAnalyzer` monitoring (§19)
- [ ] Never use SQLite session service under load (§17)
- [ ] Review prompts for token waste (§15)

---

## References

| Resource                                                                                                              | Description                                          |
| :-------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------- |
| [ADK Python Source](https://github.com/google/adk-python)                                                             | Official ADK repository                              |
| [Gemini Context Caching](https://ai.google.dev/gemini-api/docs/caching)                                               | API documentation                                    |
| [Vertex AI Context Cache](https://cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview) | Vertex documentation                                 |
| `google.adk.agents.run_config`                                                                                        | `RunConfig`, `ToolThreadPoolConfig`, `StreamingMode` |
| `google.adk.agents.context_cache_config`                                                                              | `ContextCacheConfig`                                 |
| `google.adk.agents.parallel_agent`                                                                                    | `ParallelAgent`                                      |
| `google.adk.agents.llm_agent`                                                                                         | `LlmAgent`, `static_instruction`                     |
| `google.adk.flows.llm_flows.functions`                                                                                | Parallel tool execution                              |
| `google.adk.utils.cache_performance_analyzer`                                                                         | `CachePerformanceAnalyzer`                           |
| `google.genai.types.ThinkingConfig`                                                                                   | Thinking budget control                              |
| `google.genai.types.GenerateContentConfig`                                                                            | Model config parameters                              |
