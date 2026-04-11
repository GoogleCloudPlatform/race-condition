# Planner with evaluation

Extended planner that adds LLM-as-Judge plan evaluation, simulator
coordination, and A2UI dashboard rendering. Inherits all route generation and
financial modeling capabilities from the [base planner](../planner/).

## What it adds

The base planner produces marathon plans. This variant adds three capabilities:

1. **Plan evaluation**: scores the plan across 7 criteria using Vertex AI's
   Eval API with a Gemini 3 Pro judge model, then falls back to heuristic
   scoring if the API is unavailable
2. **Simulator coordination**: sends the evaluated plan to the simulator agent
   for verification or execution via A2A
3. **A2UI dashboard**: renders structured plan and simulation result cards in
   the frontend using the A2UI v0.8.0 protocol

## Evaluation: LLM-as-Judge

The `evaluate_plan` tool scores a plan against the user's intent using 7
criteria. Six are judged by Gemini 3 Pro; one is deterministic.

### LLM-judged criteria (Vertex AI Eval API)

All six subjective criteria are evaluated in a **single API call** using a
combined LLM metric with a detailed rubric. Each criterion has 3 sub-criteria
and a 1-5 scoring scale:

| Criterion | What the judge evaluates |
|:----------|:------------------------|
| Safety compliance | Emergency access, medical support, crowd safety |
| Logistics completeness | Timing/scheduling, course support, resource staging |
| Participant experience | Route quality, spectator engagement, runner amenities |
| Community impact | Disruption mitigation, equity, community engagement |
| Financial viability | Budget planning, revenue sources, cost management |
| Intent alignment | Location match, theme/scale, specific user requests |

### Deterministic criterion

| Criterion | How it's scored |
|:----------|:----------------|
| Distance compliance | Exact 26.2 miles = 5.0, deviation > 0.5 miles = 1.0 |

### Score normalization

Raw scores (1-5 from the API, 0-100 from heuristics) are normalized to a
0-100 scale. The overall score is a weighted average (equal weights). A plan
passes if the overall score is >= 75 and there are no high-severity findings
(score < 40).

### Heuristic fallback

When the Vertex AI Eval API is unavailable, a keyword-based scorer runs
instead. Each criterion has a base score (70-85) adjusted by keyword bonuses
and red-flag penalties. This ensures the evaluation tool always returns a
result.

### LLM feedback

After scoring, a separate Gemini call generates actionable improvement
suggestions (e.g., "Add emergency vehicle crossing points at miles 5, 10, 15,
and 20"). Falls back to pre-written suggestions per criterion if the LLM call
fails.

## Simulator coordination

Two tools manage the simulator lifecycle:

**`start_simulation`** -- lightweight, returns immediately. Generates a UUID
`simulation_id` and writes it to session state so telemetry dashboards can
track the simulation before it starts running.

**`submit_plan_to_simulator`** -- calls the simulator agent via A2A with two
possible actions:

| Action | What happens |
|:-------|:-------------|
| `verify` | Validates plan readiness without spawning runners |
| `execute` | Spawns runners, runs the full tick loop |

Route GeoJSON and traffic assessments are stored in a Redis side-channel
(`simdata`) to avoid bloating the A2A payload. If Redis is unavailable, the
data is included inline as a fallback.

### Concurrency handling

Both tools can be called in the same LLM response (parallel tool calling).
`submit_plan_to_simulator` polls for `start_simulation` to finish writing
the simulation token (up to 2 seconds). If the LLM skips `start_simulation`,
`submit_plan_to_simulator` calls it internally.

A re-entrancy guard prevents duplicate executions within the same LLM turn
using an `invocation_id`-scoped session state key. New user messages (new
invocations) allow legitimate re-runs.

## A2UI dashboard

The agent renders two card types using the `validate_and_emit_a2ui` shared
tool:

**Plan dashboard card** (`surfaceId: "dashboard"`):
- Header with plan number and route name
- Overall evaluation score
- 7-criterion scoring grid (2-column layout)
- Findings with severity labels (MAJOR/MODERATE)
- "Run Simulation" action button

**Simulation results card** (`surfaceId: "sim_results"`):
- Simulation ID and timestamp
- Distance, participants, spectators, peak hour volume
- Safety score, runner experience, city disruption metrics
- "Re-run Simulation" action button

Cards are composed generatively by the LLM using one-shot examples in the
prompt, then validated and emitted by the shared A2UI tool.

## Prompt architecture

Uses `PromptBuilder.override()` on the base planner's prompt:

| Section | Status | Content |
|:--------|:-------|:--------|
| `role` | inherited | Marathon architect identity |
| `rules` | inherited | Pragmatic personality, output format |
| `skills` | inherited | Skill loading instructions |
| `tools` | **overridden** | Adds evaluator guidance, scoring descriptions |
| `workflow` | **overridden** | 9-step workflow (adds evaluation, A2UI, STOP) |
| `financial` | inherited | Financial modeling modes |
| `simulator` | **added** | Simulator tool docs, actions, runner types |
| `a2ui` | **added** | A2UI v0.8.0 format reference with examples |
| `execution` | **added** | Simulation execution flow (physically separated from workflow) |

The `execution` section is deliberately separated from `workflow` to prevent
LLM completion pressure from skipping the STOP directive at the end of
planning. The LLM should stop after evaluating the plan and rendering the
dashboard -- it only enters the execution section when the user triggers
simulation.

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` / `PLANNER_WITH_EVAL_PORT` | `8205` | HTTP listen port |
| `EVALUATOR_MODEL` | `gemini-3-pro-preview` | Judge model for evaluation |
| `GOOGLE_CLOUD_PROJECT` | -- | GCP project (required for Vertex AI Eval) |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini API endpoint |

## File layout

```
agents/planner_with_eval/
├── agent.py                 # root_agent, A2A deployment, server startup
├── prompts.py               # PromptBuilder overrides (5 sections)
├── tools.py                 # start_simulation, submit_plan_to_simulator
├── adk_tools.py             # Full tool registry assembly
├── evaluator/
│   ├── config.py            # Model, criteria, weights, thresholds
│   └── tools.py             # evaluate_plan implementation (~800 lines)
├── tests/
│   ├── test_submit_plan.py
│   ├── test_eval_integration.py
│   ├── test_eval_feedback.py
│   ├── test_relocation.py
│   ├── test_planner_with_eval_prompts.py
│   ├── test_a2ui_migration.py
│   └── test_integration.py
└── evals/
    └── test_trajectory.py   # ADK trajectory evaluation
```

## Further reading

- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluate-models) --
  the API used for LLM-as-Judge scoring
- [A2UI protocol](../utils/a2ui.py) -- component builder for dashboard cards
- The base planner ([agents/planner/](../planner/)) provides inherited route
  generation and financial modeling
- The simulator ([agents/simulator/](../simulator/)) receives plans for
  verification and execution
