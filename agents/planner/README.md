# Planner agent

ADK-powered marathon planning agent that generates precise 26.2-mile routes on
real Las Vegas road network data, places course infrastructure to World
Athletics standards, and manages event logistics and financial modeling.

## What it does

The planner is the simulation's city marathon architect. Given a planning
request (or no request at all -- it defaults to Las Vegas), it:

1. Loads GIS skills and generates an exact 26.2188-mile marathon route
2. Places hydration stations (every 5 km per World Athletics TR 55), medical
   tents, portable toilets, and cheer zones automatically
3. Plans event logistics (theme, start time, wave count, water stations)
4. Optionally assesses traffic impact on the road network
5. Produces a natural-language plan covering safety, community impact,
   logistics, participant experience, and financial viability

The planner follows an "assume and go" philosophy: it defaults to Las Vegas,
nighttime start, 10,000 participants, and a moderate budget. It never asks
clarifying questions for optional details.

## Route generation

The core tool is `plan_marathon_route` in the `gis-spatial-engineering` skill.
It operates on a Las Vegas road network stored as GeoJSON
(`skills/gis-spatial-engineering/assets/network.json`) containing landmarks,
roads, and motorways.

The **zone-sweep algorithm** (default):

1. Start on Las Vegas Boulevard (the Strip) heading northbound
2. Serpentine through surrounding neighborhoods in systematic zone sweeps
3. Detect and prevent road crossings using segment intersection checks
4. Return to a finish landmark near the start

The route is built by constructing a weighted graph from GeoJSON LineString
features, then finding shortest paths between waypoints using Dijkstra's
algorithm. The result is a GeoJSON FeatureCollection with the route polyline
and all course infrastructure features.

Routes are **idempotent**: calling `plan_marathon_route` twice with the same
seed returns the cached route from session state.

## Skills

Skills are loaded on demand via ADK's `SkillToolset`. Each skill directory
contains a `SKILL.md` manifest and a `scripts/tools.py` with tool functions.

| Skill | Tools | Purpose |
|:------|:------|:--------|
| `gis-spatial-engineering` | `plan_marathon_route`, `report_marathon_route` | Route generation, course infrastructure, route reporting |
| `race-director` | `plan_marathon_event` | Event characteristics (theme, start time, waves) |
| `mapping` | (Maps MCP tools) | Google Maps Grounding Lite: place search, route computation, weather lookup |
| `insecure-financial-modeling` | (prompt-only) | Shares budget percentages, approves changes |
| `secure-financial-modeling` | (prompt-only) | Refuses all budget modifications |

Planning skills and financial skills are isolated by design. Financial skills
are never loaded during the planning workflow -- they're user-triggered only.

## Financial guardrail

The planner has a programmatic `before_model_callback` that enforces financial
modeling rules. In "secure" mode, it blocks any user message containing both a
financial noun (budget, cost, revenue, etc.) and a write verb (change, modify,
increase, etc.). The mode is toggled via the `set_financial_modeling_mode` tool.

This is a hard programmatic block, not a prompt-based instruction. The model
never sees the blocked request.

## Prompt architecture

The system instruction is built using `PromptBuilder` with 6 named sections:

| Section | Content |
|:--------|:--------|
| `role` | Identity, core requirements, algorithm description |
| `rules` | Personality (pragmatic, detail-oriented), output format |
| `skills` | Skill loading instructions, planning vs financial isolation |
| `tools` | Default parameters, deliverables, quality pillars |
| `workflow` | 7-step sequential planning process |
| `financial` | Financial modeling mode docs, turn isolation rules |

The `PromptBuilder` is immutable with override support. Downstream variants
(`planner_with_eval`, `planner_with_memory`) inherit the base prompt and
override or extend specific sections without duplicating the rest.

## Agent variants

This is the **base planner** -- a standalone planning agent that produces
marathon plans but does not coordinate with the simulator or runners. Two
extended variants build on top of it:

| Variant | Added capabilities |
|:--------|:-------------------|
| [planner_with_eval](../planner_with_eval/) | Simulator coordination, A2UI dashboard, traffic assessment, LLM-as-Judge evaluation |
| [planner_with_memory](../planner_with_memory/) | AlloyDB persistent memory, route storage/recall, cross-session learning |

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` / `PLANNER_PORT` | `8204` | HTTP listen port |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini API endpoint |
| `GOOGLE_CLOUD_PROJECT` | -- | GCP project (enables Maps MCP tools) |
| `GOOGLE_MAPS_API_KEY` | -- | Maps API key (env var or Secret Manager) |

## Running locally

```bash
# Standalone
uv run python -m agents.planner.agent

# Via Honcho (recommended)
honcho start planner
```

## File layout

```
agents/planner/
├── agent.py                    # root_agent, A2A deployment, server startup
├── adk_tools.py                # Tool registry (SkillToolset, Maps MCP, financial toggle)
├── prompts.py                  # PromptBuilder with 6 sections
├── callbacks.py                # Financial guardrail before_model_callback
├── planner_agent_test.py       # Agent export, card, route integration tests
├── tests/
│   ├── test_planner_tools.py   # Tool tests (~1240 lines)
│   ├── test_planner_prompts.py # Prompt validation tests
│   ├── test_financial_guardrail.py
│   ├── test_financial_modeling.py
│   └── test_traffic_assessment.py
├── evals/
│   ├── test_planner_evals.py           # ADK trajectory evaluations
│   ├── test_financial_modeling_e2e.py   # E2E financial mode tests
│   ├── planner_trajectory.test.json    # Eval dataset
│   └── test_config.json                # Eval config
└── skills/
    ├── gis-spatial-engineering/    # Route generation (~2350 lines)
    ├── race-director/             # Event logistics
    ├── mapping/                   # Maps MCP (no scripts, uses Agent Registry)
    ├── insecure-financial-modeling/  # Permissive financial skill
    └── secure-financial-modeling/   # Restrictive financial skill
```

## Testing

- **Unit tests**: tool behavior, prompt structure, guardrail logic
- **Integration tests**: route generation with mocked LLM
- **Evaluations** (`make eval`): ADK trajectory evaluations against live
  Gemini API. Two eval cases test standard planning and plan-without-execution
  workflows.

## Further reading

- [Google ADK](https://google.github.io/adk-docs/) -- Agent Development Kit
- [ADK Skills](https://google.github.io/adk-docs/tools/skills/) -- skill
  loading and toolset patterns
- [World Athletics Technical Rules](https://worldathletics.org/about/documents/technical-information) --
  the standards behind hydration station placement
- The shared utilities ([agents/utils/](../utils/)) provide the plugin system,
  dispatcher, and communication layer
