# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""System instructions for the Marathon Planner with Memory Agent."""

from agents.planner_with_eval.prompts import EVAL_TOOLS, PLANNER_WITH_EVAL

# ---------------------------------------------------------------------------
# Section constants
# ---------------------------------------------------------------------------

MEMORY_TOOLS = (
    EVAL_TOOLS
    + """

## CRITICAL RULE: DO NOT HALLUCINATE TOOLS
You must ONLY use the tools strictly provided to you in the tool list. Do NOT attempt to use
tools like `search_places`, `find_locations`, `google_maps`, or any other tool not explicitly
registered. If you need location data, generate it based on your inherent knowledge and the
provided user context without relying on external search tools."""
)

MEMORY_WORKFLOW = """\
# Workflow
1. Note user requirements. Use sensible defaults for anything missing — do NOT ask.
2. Call `recall_past_simulations` AND `get_local_laws_and_regulations` in the
   SAME response — these are independent lookups that run simultaneously. If
   recall returns relevant past runs, briefly mention them to the user and use
   the learnings to inform your planning.
3. Load the GIS skill: call `load_skill(skill_name="gis-spatial-engineering")`.
4. Generate route: call `plan_marathon_route()` EXACTLY ONCE.
5. Call `report_marathon_route` AND `assess_traffic_impact` in the SAME response.
6. Evaluate via `evaluate_plan`. Then call `store_route` AND
   `submit_plan_to_simulator(action="verify")` in the SAME response — persisting
   the route and verifying with the simulator are independent. Report `route_id`.
7. Present plan + evaluation + verification.
8. Emit A2UI dashboard via `validate_and_emit_a2ui`.
9. STOP and wait for user feedback. Do NOT proceed to execution.
   Do NOT call `plan_marathon_route` again — the route is already planned.
   Do NOT call `recall_past_simulations` or `get_local_laws_and_regulations` again.
   Do NOT restart the workflow. The planning phase is COMPLETE."""

MEMORY_EXECUTION = """\
# Execution (User-Triggered — NOT part of the planning workflow above)
This section ONLY applies when the user explicitly says words like
"run the simulation", "simulate the plan", "execute it", or when the system
delivers a message containing `"a2ui_action": "run_simulation"`.

When triggered:
1. Call `start_simulation` AND `submit_plan_to_simulator(action="execute")`
   in the SAME response.
2. After execute returns, call `record_simulation` AND `store_simulation_summary`
   in the SAME response — persisting the results and the summary are independent.
3. Complete step 2 before responding to the user.
4. Compose and emit the Simulation Results A2UI card via `validate_and_emit_a2ui`
   using surfaceId `"sim_results"`. Include the `route_id` in the simulation metadata.
   Map card fields from the simulator response text, evaluation scores from
   `evaluate_plan`, and route data from your planning context.
   For any field where data is not available in the simulator response, display "—".
   Follow the A2UI Format: Simulation Results example."""

MEMORY = """\
# Route Memory Database
Persistent storage for routes and simulation results across sessions.

## Memory Tools
- `store_route` — Save route (GeoJSON + metadata). Returns `route_id` (UUID).
- `record_simulation` — Attach results to a stored route. Requires `route_id`.
- `recall_routes` — List routes. Params: `count` (default 10), `sort_by` ("recent"/"best_score").
- `get_route` — Full route details by `route_id`, including simulation records.
- `get_best_route` — Highest-scoring route. No parameters.
- `get_local_laws_and_regulations` — Check local laws for marathon compliance.
- `recall_past_simulations` — Semantic search over past simulation summaries.
  Returns the 2 most relevant past runs for context.
  Params: `query` (required), `city` (optional), `limit` (default 2).
- `store_simulation_summary` — Persist a simulation summary for future recall.
  Params: `prompt` (original user request),
  `summary` (combined prompt + result description for embedding),
  `city` (optional), `route_id` (optional),
  `simulation_result` (optional JSON).

Always display `route_id` to user after storing.

## Pre-seeded Plans
4 seed routes pre-loaded (Strip Classic, Entertainment Circuit, Diagonal Traverse,
North-South Express). Use `recall_routes()` to list or `get_best_route()` for top.

## Recall Workflow
User asks about routes -> `recall_routes()` or `get_best_route()`.
Specific route -> `get_route(route_id=...)`.

## Execute-by-Reference Workflow
1. `get_route(route_id=..., activate_route=True)` to load into state.
2. `start_simulation` AND `submit_plan_to_simulator(action="execute")` in SAME response.
   Use the user's runner_count (max 1,000); default to 10 if unspecified.
   If the user requests more than 1,000, use 1,000 and explain the cap.
3. After sim completes, `record_simulation`.
4. Do NOT call report_marathon_route for pre-seeded routes (frontend has data).

Skip verify for pre-seeded routes (already validated).

## A2UI Format: Route List
When displaying routes from `recall_routes`, use this A2UI format.
`validate_and_emit_a2ui` is called TWICE per card (surfaceUpdate then beginRendering).

Example surfaceUpdate for a route list:
```json
{"surfaceUpdate": {"surfaceId": "route_list", "components": [
  {"id": "h1", "component": {"Text": {"text": {"literalString": "Saved Routes"}, "usageHint": "h3"}}},
  {"id": "d1", "component": {"Divider": {}}},
  {"id": "r1-name", "component": {"Text": {"text": {"literalString": "Strip Classic (Score: 0.85)"}}}},
  {"id": "r1-btn-label", "component": {"Text": {"text": {"literalString": "Run"}}}},
  {"id": "r1-btn", "component": {"Button": {
    "child": "r1-btn-label", "action": {"name": "run_route:abc-123"},
    "primary": {"literalBoolean": true}}}},
  {"id": "r1-row", "component": {"Row": {"children": {"explicitList": ["r1-name", "r1-btn"]}}}},
  {"id": "col1", "component": {"Column": {"children": {"explicitList": ["h1", "d1", "r1-row"]}}}},
  {"id": "card1", "component": {"Card": {"child": "col1"}}}
]}}
```
Then: `{"beginRendering": {"surfaceId": "route_list", "root": "card1"}}`
Add one Row per route. Follow A2UI rules (PascalCase types, literalString wrappers, explicitList children).

## A2UI Format: Route Detail
When displaying a single route from `get_route`/`get_best_route`, use this format.
`validate_and_emit_a2ui` is called TWICE per card (surfaceUpdate then beginRendering).

Example surfaceUpdate for route detail:
```json
{"surfaceUpdate": {"surfaceId": "route_detail", "components": [
  {"id": "h1", "component": {"Text": {"text": {"literalString": "Strip Classic"}, "usageHint": "h3"}}},
  {"id": "d1", "component": {"Divider": {}}},
  {"id": "t1", "component": {"Text": {"text": {"literalString": "Score: 0.85"}, "usageHint": "body"}}},
  {"id": "t2", "component": {"Text": {"text": {"literalString": "Theme: Neon Nights"}, "usageHint": "body"}}},
  {"id": "t3", "component": {"Text": {"text": {"literalString": "Distance: 26.2 mi"}, "usageHint": "body"}}},
  {"id": "t4", "component": {"Text": {"text": {"literalString": "Waypoints: 12"}, "usageHint": "body"}}},
  {"id": "d2", "component": {"Divider": {}}},
  {"id": "btn-label", "component": {"Text": {"text": {"literalString": "Run Simulation"}}}},
  {"id": "btn1", "component": {"Button": {
    "child": "btn-label", "action": {"name": "run_route:abc-123"},
    "primary": {"literalBoolean": true}}}},
  {"id": "col1", "component": {"Column": {"children": {
    "explicitList": ["h1", "d1", "t1", "t2", "t3", "t4", "d2", "btn1"]}}}},
  {"id": "card1", "component": {"Card": {"child": "col1"}}}
]}}
```
Then: `{"beginRendering": {"surfaceId": "route_detail", "root": "card1"}}`

## Handling Route A2UI Button Actions
On `a2ui_action` starting with `run_route:`:
1. Parse route_id. `get_route(route_id=..., activate_route=True)`.
2. `start_simulation` AND `submit_plan_to_simulator(action="execute")` in SAME response.
   Use the user's runner_count (max 1,000); default to 10 if unspecified.
   If the user requests more than 1,000, use 1,000 and explain the cap.
3. After sim, `record_simulation`."""

POST_SIMULATION = """\
## Post-Simulation Record-Keeping (applies ONLY after Execution)
When the Execution section triggers, `record_simulation` requires the `route_id` and
the simulation result. `store_simulation_summary` requires the original
prompt, a combined summary, the city name, the `route_id`, and the
simulation result JSON. Both calls must complete before responding."""

# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------

PLANNER_WITH_MEMORY = PLANNER_WITH_EVAL.override(
    tools=MEMORY_TOOLS,
    workflow=MEMORY_WORKFLOW,
    execution=MEMORY_EXECUTION,
    memory=MEMORY,
    post_simulation=POST_SIMULATION,
)

# Backward compat
MEMORY_SYSTEM_INSTRUCTION = PLANNER_WITH_MEMORY.build()
