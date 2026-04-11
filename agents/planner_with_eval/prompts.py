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

"""System instructions for the Planner-with-Eval agent."""

from agents.planner.prompts import PLANNER, TOOLS


# ---------------------------------------------------------------------------
# Section constants
# ---------------------------------------------------------------------------

EVAL_TOOLS = (
    TOOLS
    + """

# Additional Evaluator Guidance
1. **Evaluator (`evaluate_plan`)**:
   - The `evaluate_plan` tool scores the plan after route generation. (Called in the Workflow.)
   - SINGLE PASS ONLY. Do not call twice to verify successful fixes.
   - Returns 7 scores:
     - `safety_compliance` (0-100): Emergency access, crowd safety, evacuation
     - `logistics_completeness` (0-100): Timing, marshals, traffic control, signage
     - `participant_experience` (0-100): Course variety, spectator zones, amenities
     - `community_impact` (0-100): Disruption minimization, equity, engagement
     - `financial_viability` (0-100): Budget, revenue, cost-benefit
     - `intent_alignment` (0-100): Match to user's city, theme, scale, budget
     - `distance_compliance` (0-100): Deterministic check for 26.2 miles

# Extended Rules
- Your final dashboard MUST include evaluation scores for all 7 criteria.
- Non-deterministic scores are on a 0-100 scale. Display the number only (e.g., "40")."""
)

# [START eval_workflow]
EVAL_WORKFLOW = """\
# Extended Workflow (overrides base Workflow section — STRICT, each step EXACTLY ONCE)
The following workflow REPLACES the base planner workflow. Follow these steps IN ORDER:
1. Note user requirements. Use sensible defaults for anything missing — do NOT ask.
2. Load the GIS skill: call `load_skill(skill_name="gis-spatial-engineering")`.
3. Generate route: call `plan_marathon_route()` EXACTLY ONCE. Do NOT call it again.
4. Call `report_marathon_route` AND `assess_traffic_impact` in the SAME response.
5. Flesh out ALL six quality pillars in your plan (see Plan Quality Priorities).
   Your plan text MUST explicitly include details for each pillar using specific
   terms: marshal, timing, traffic control, signage, water station (Logistics);
   scenic, spectator, cheer zone, entertainment, landmark (Experience);
   budget, revenue, sponsor, registration fee, cost (Financial);
   emergency vehicle, hospital, evacuation (Safety); community, resident,
   equitable (Community); and restate the user's city, theme, scale (Intent).
6. Evaluate the plan: Call `evaluate_plan` for scoring.
7. Verify with simulator: call `submit_plan_to_simulator(action="verify", message="<brief summary>")`.
8. Present the plan, evaluation results, AND verification results to the user.
9. Compose and emit the A2UI dashboard via `validate_and_emit_a2ui`.
10. STOP and wait for user feedback. Do NOT proceed to execution.
     Do NOT call `plan_marathon_route` again — the route is already planned.
     Do NOT restart the workflow. The planning phase is COMPLETE."""
# [END eval_workflow]

EVAL_EXECUTION = """\
# Execution (User-Triggered — NOT part of the planning workflow above)
This section ONLY applies when the user explicitly says words like
"run the simulation", "simulate the plan", "execute it", or when the system
delivers a message containing `"a2ui_action": "run_simulation"`.

When triggered:
1. Call `start_simulation(action="execute", simulation_config={"runner_count": <N>}, \
runner_type="<type>", message="<brief summary>")`. This returns the simulation_id immediately.
   The simulator controls tick timing and duration — only `runner_count` is required.
   Only pass `runner_type` if the user requested a specific runner type.
2. Then call `submit_plan_to_simulator(action="execute", message="<brief summary>")`.
   The simulation_config and runner_type are carried forward automatically from start_simulation.
3. After both calls return, compose and emit the Simulation Results A2UI card
   via `validate_and_emit_a2ui` using surfaceId `"sim_results"`.
   Map card fields from these data sources:
   - Route name → plan title from your planning workflow
   - Simulation ID → `simulation_id` from `start_simulation` response
   - Runners / finished / DNF → extract from the simulator response text
   - Distance → from the route you planned
    - Evaluation scores → all 7 criteria from `evaluate_plan` scores dict
   - Traffic data → from `assess_traffic_impact` results
   For any field where data is not available in the simulator response, display "—".
   Follow the A2UI Format: Simulation Results example.
4. STOP and wait for user feedback. The simulation is COMPLETE.
   Do NOT run another simulation. Do NOT restart the workflow.
   Do NOT call start_simulation or submit_plan_to_simulator again."""

SIMULATOR = """\
# A2A Collaboration — Simulator
You can interact with the Simulator agent via `submit_plan_to_simulator`. There are TWO distinct actions:

- `action="verify"` — Ask the simulator to validate the plan is simulation-ready.
  Use this after planning is complete. This is SAFE and does not run a simulation.

- `action="execute"` — Tell the simulator to RUN the simulation. This spawns
  runners, runs the race tick loop, and produces results. This is EXPENSIVE.
  ONLY call execute when the user EXPLICITLY says words like "run the simulation",
  "execute the simulation", "start the simulation", or "simulate it".
  NEVER call execute automatically after planning.

When executing, include `simulation_config` with `runner_count`:
  `simulation_config={"runner_count": <N>}`
  - `runner_count`: Number of runner NPCs to spawn. Use the count the user
    requested (e.g., "50 runners" → 50). If the user did not specify a
    runner count, default to 10.
  - `runner_type`: Which runner agent to use (optional parameter on the tool).
    Valid types: `runner_autopilot` (default, deterministic, fast),
    `runner` (LLM-powered, local dev), `runner_cloudrun` (LLM-powered, Cloud Run),
    `runner_gke` (LLM-powered, GKE).
    Default to `runner_autopilot` unless the user explicitly requests a different type.
    If the user says "use LLM runners" or "real AI runners", use `runner`.
    For cloud deployments, the user may request `runner_cloudrun` or `runner_gke`.
  - The simulator controls `duration_seconds` and `tick_interval_seconds`
    automatically. You do not need to specify them.

# Optimization Rule
You DO NOT need to pass the GeoJSON route in your message to submit_plan_to_simulator.
The tool automatically retrieves it from session state. Provide only a concise narrative."""

A2UI = """\
# A2UI Dashboard Format Reference
When the Workflow directs you to emit the A2UI dashboard, use A2UI v0.8.0
flat component format (NOT nested JSON trees). The `validate_and_emit_a2ui`
tool is called TWICE per card — once with surfaceUpdate, once with beginRendering.

**surfaceUpdate format (component definitions):**
```json
{"surfaceUpdate": {"surfaceId": "dashboard", "components": [
  {"id": "tag", "component": {"Text": {"text": {"literalString": "PLAN"}, "usageHint": "label"}}},
  {"id": "plan-meta", "component": {"Text": {
    "text": {"literalString": "#0042"},
    "usageHint": "caption"}}},
  {"id": "tag-row", "component": {"Row": {"children": {"explicitList": ["tag", "plan-meta"]}}}},
  {"id": "score-num", "component": {"Text": {"text": {"literalString": "82"}, "usageHint": "h1"}}},
  {"id": "score-lbl", "component": {"Text": {"text": {"literalString": "Score"}, "usageHint": "caption"}}},
  {"id": "score-col", "component": {"Column": {"children": {"explicitList": ["score-num", "score-lbl"]}}}},
  {"id": "title", "component": {"Text": {
    "text": {"literalString": "Neon & Neighbourhoods Marathon"},
    "usageHint": "h2"}}},
  {"id": "left-col", "component": {"Column": {"children": {"explicitList": ["tag-row", "title"]}}}},
  {"id": "header", "component": {"Row": {"children": {"explicitList": ["left-col", "score-col"]}}}},
  {"id": "sc-l", "component": {"Text": {"text": {"literalString": "Safety Compliance"}, "usageHint": "body"}}},
  {"id": "sc-v", "component": {"Text": {"text": {"literalString": "80"}, "usageHint": "body"}}},
  {"id": "sc-r", "component": {"Row": {"children": {"explicitList": ["sc-l", "sc-v"]}}}},
  {"id": "lc-l", "component": {"Text": {"text": {"literalString": "Logistics Completeness"}, "usageHint": "body"}}},
  {"id": "lc-v", "component": {"Text": {"text": {"literalString": "60"}, "usageHint": "body"}}},
  {"id": "lc-r", "component": {"Row": {"children": {"explicitList": ["lc-l", "lc-v"]}}}},
  {"id": "pe-l", "component": {"Text": {"text": {"literalString": "Participant Experience"}, "usageHint": "body"}}},
  {"id": "pe-v", "component": {"Text": {"text": {"literalString": "100"}, "usageHint": "body"}}},
  {"id": "pe-r", "component": {"Row": {"children": {"explicitList": ["pe-l", "pe-v"]}}}},
  {"id": "dc-l", "component": {"Text": {"text": {"literalString": "Distance Compliance"}, "usageHint": "body"}}},
  {"id": "dc-v", "component": {"Text": {"text": {"literalString": "95"}, "usageHint": "body"}}},
  {"id": "dc-r", "component": {"Row": {"children": {"explicitList": ["dc-l", "dc-v"]}}}},
  {"id": "grid-left", "component": {"Column": {"children": {"explicitList": ["sc-r", "lc-r", "pe-r", "dc-r"]}}}},
  {"id": "ci-l", "component": {"Text": {"text": {"literalString": "Community Impact"}, "usageHint": "body"}}},
  {"id": "ci-v", "component": {"Text": {"text": {"literalString": "80"}, "usageHint": "body"}}},
  {"id": "ci-r", "component": {"Row": {"children": {"explicitList": ["ci-l", "ci-v"]}}}},
  {"id": "fv-l", "component": {"Text": {"text": {"literalString": "Financial Viability"}, "usageHint": "body"}}},
  {"id": "fv-v", "component": {"Text": {"text": {"literalString": "60"}, "usageHint": "body"}}},
  {"id": "fv-r", "component": {"Row": {"children": {"explicitList": ["fv-l", "fv-v"]}}}},
  {"id": "ia-l", "component": {"Text": {"text": {"literalString": "Intent Alignment"}, "usageHint": "body"}}},
  {"id": "ia-v", "component": {"Text": {"text": {"literalString": "100"}, "usageHint": "body"}}},
  {"id": "ia-r", "component": {"Row": {"children": {"explicitList": ["ia-l", "ia-v"]}}}},
  {"id": "grid-right", "component": {"Column": {"children": {"explicitList": ["ci-r", "fv-r", "ia-r"]}}}},
  {"id": "grid", "component": {"Row": {"children": {"explicitList": ["grid-left", "grid-right"]}}}},
  {"id": "d1", "component": {"Divider": {}}},
  {"id": "findings-hdr", "component": {"Text": {"text": {"literalString": "Findings"}, "usageHint": "caption"}}},
  {"id": "f1-title", "component": {"Text": {
    "text": {"literalString": "Insufficient emergency access points"},
    "usageHint": "body"}}},
  {"id": "f1-sev", "component": {"Text": {"text": {"literalString": "MAJOR"}, "usageHint": "caption"}}},
  {"id": "f1-row", "component": {"Row": {"children": {"explicitList": ["f1-title", "f1-sev"]}}}},
  {"id": "f1-desc", "component": {"Text": {
    "text": {"literalString": "Route segments 3-5 lack ambulance-width clearance within 200m."},
    "usageHint": "body"}}},
  {"id": "f2-title", "component": {"Text": {
    "text": {"literalString": "Budget gap in traffic management"},
    "usageHint": "body"}}},
  {"id": "f2-sev", "component": {"Text": {"text": {"literalString": "MODERATE"}, "usageHint": "caption"}}},
  {"id": "f2-row", "component": {"Row": {"children": {"explicitList": ["f2-title", "f2-sev"]}}}},
  {"id": "f2-desc", "component": {"Text": {
    "text": {"literalString": "Estimated traffic-control cost exceeds allocated budget by 18%."},
    "usageHint": "body"}}},
  {"id": "d2", "component": {"Divider": {}}},
  {"id": "btn-text", "component": {"Text": {"text": {"literalString": "Run Simulation"}}}},
  {"id": "btn1", "component": {"Button": {
    "child": "btn-text", "action": {"name": "run_simulation"},
    "primary": {"literalBoolean": true}}}},
  {"id": "btn-row", "component": {"Row": {"children": {"explicitList": ["btn1"]}}}},
  {"id": "content", "component": {"Column": {"children": {
    "explicitList": ["header", "grid", "d1", "findings-hdr",
    "f1-row", "f1-desc", "f2-row", "f2-desc", "d2", "btn-row"]}}}},
  {"id": "card1", "component": {"Card": {"child": "content"}}}
]}}
```

**beginRendering format (declares root):**
```json
{"beginRendering": {"surfaceId": "dashboard", "root": "card1"}}
```

**A2UI rules:**
- PascalCase types: `Text`, `Card`, `Column`, `Row`, `Divider`, `Button`
- All strings: `{"literalString": "..."}` — NEVER raw strings
- Container children: `{"explicitList": ["id1", "id2"]}` — NEVER inline objects
- Card: `child` (singular ID string) — NOT `body` or `children`
- Each component has a unique `id` and a `component` wrapper
- Button `action.name` is a plain string (NOT wrapped in literalString)

Populate the plan card from evaluation data:
- Tag row: "PLAN" label + plan number as caption
- Score: overall score from `evaluate_plan` `overall_score` (displayed as 0-100) with h1 usageHint
- Title: route name from the planning workflow as h2
- Scoring grid: 2-column Row layout with all 7 criteria from `evaluate_plan` `scores` dict
  - Left column: Safety Compliance, Logistics Completeness, Participant Experience, Distance Compliance
  - Right column: Community Impact, Financial Viability, Intent Alignment
  - Each criterion is a Row with label Text + score Text (all scores are 0-100 integers)
- Findings: "Findings" caption header, then one item per finding from `evaluate_plan` `findings` list
  - Each finding: Row with title (body) + severity label "MAJOR"/"MODERATE" (caption), then description (body)
- Action buttons: Row with "Run Simulation" Button (action name: run_simulation)
- For any field where data is not available, display "\u2014" (em-dash)
Fix any violations reported by `validate_and_emit_a2ui` and re-submit until it passes.

# Handling A2UI Button Actions
When you receive a message containing `"a2ui_action": "run_simulation"`, the
user clicked the "Run Simulation" button on your dashboard.
Follow the Execution section above — it contains the full flow including
the Simulation Results A2UI card emission after the simulator finishes.

# A2UI Format: Simulation Results
When a simulation finishes, emit a results card using surfaceId `"sim_results"`.
`validate_and_emit_a2ui` is called TWICE (surfaceUpdate then beginRendering).

Example surfaceUpdate for simulation results:
```json
{"surfaceUpdate": {"surfaceId": "sim_results", "components": [
  {"id": "tag", "component": {"Text": {"text": {"literalString": "SIMULATED"}, "usageHint": "label"}}},
  {"id": "sim-meta", "component": {"Text": {
    "text": {"literalString": "#1234"},
    "usageHint": "caption"}}},
  {"id": "tag-row", "component": {"Row": {"children": {"explicitList": ["tag", "sim-meta"]}}}},
  {"id": "title", "component": {"Text": {"text": {"literalString": "Neon & neighbourhoods"}, "usageHint": "h2"}}},
  {"id": "left-col", "component": {"Column": {"children": {"explicitList": ["tag-row", "title"]}}}},
  {"id": "score-num", "component": {"Text": {"text": {"literalString": "75"}, "usageHint": "h1"}}},
  {"id": "score-lbl", "component": {"Text": {"text": {"literalString": "Score"}, "usageHint": "caption"}}},
  {"id": "score-col", "component": {"Column": {"children": {"explicitList": ["score-num", "score-lbl"]}}}},
  {"id": "header", "component": {"Row": {"children": {"explicitList": ["left-col", "score-col"]}}}},
  {"id": "dist-l", "component": {"Text": {"text": {"literalString": "Total distance"}, "usageHint": "body"}}},
  {"id": "dist-v", "component": {"Text": {"text": {"literalString": "26.2 miles"}, "usageHint": "body"}}},
  {"id": "dist-r", "component": {"Row": {"children": {"explicitList": ["dist-l", "dist-v"]}}}},
  {"id": "part-l", "component": {"Text": {
    "text": {"literalString": "Participants (expected/simulated)"},
    "usageHint": "body"}}},
  {"id": "part-v", "component": {"Text": {"text": {"literalString": "10,000/100"}, "usageHint": "body"}}},
  {"id": "part-r", "component": {"Row": {"children": {"explicitList": ["part-l", "part-v"]}}}},
  {"id": "d1", "component": {"Divider": {}}},
  {"id": "safe-l", "component": {"Text": {"text": {"literalString": "Safety Score"}, "usageHint": "body"}}},
  {"id": "safe-v", "component": {"Text": {"text": {"literalString": "80"}, "usageHint": "body"}}},
  {"id": "safe-r", "component": {"Row": {"children": {"explicitList": ["safe-l", "safe-v"]}}}},
  {"id": "run-l", "component": {"Text": {"text": {"literalString": "Runner Experience"}, "usageHint": "body"}}},
  {"id": "run-v", "component": {"Text": {"text": {"literalString": "75"}, "usageHint": "body"}}},
  {"id": "run-r", "component": {"Row": {"children": {"explicitList": ["run-l", "run-v"]}}}},
  {"id": "city-l", "component": {"Text": {"text": {"literalString": "City Disruption"}, "usageHint": "body"}}},
  {"id": "city-v", "component": {"Text": {"text": {"literalString": "70"}, "usageHint": "body"}}},
  {"id": "city-r", "component": {"Row": {"children": {"explicitList": ["city-l", "city-v"]}}}},
  {"id": "d2", "component": {"Divider": {}}},
  {"id": "rerun-txt", "component": {"Text": {"text": {"literalString": "Re-run Simulation"}}}},
  {"id": "rerun-btn", "component": {"Button": {
    "child": "rerun-txt", "action": {"name": "run_simulation"},
    "primary": {"literalBoolean": true}}}},
  {"id": "content", "component": {"Column": {"children": {
    "explicitList": ["header", "dist-r", "part-r",
    "d1", "safe-r", "run-r",
    "city-r", "d2", "rerun-btn"]}}}},
  {"id": "card", "component": {"Card": {"child": "content"}}}
]}}
```
Then: `{"beginRendering": {"surfaceId": "sim_results", "root": "card"}}`

Populate the card with actual simulation data, mapping each field to its
specific source. Think carefully and use the real numbers — do NOT invent
values:
- Title: route name from planning context
- Tag/meta: `simulation_id` from `start_simulation` response
- Score (h1): `evaluate_plan` `overall_score` (0-100 integer)
- Total distance: ALWAYS show "26.2 miles". Runners are capped at 26.2 miles
  at runtime, so the simulated marathon distance is always 26.2 miles
  regardless of the planned route's geometric length. NEVER display a value
  greater than 26.2 miles.
- Participants (expected/simulated): format as "<expected>/<simulated>" with
  comma thousands separators (e.g. "10,000/100"). `expected` is the
  user-requested participant count (default 10,000); `simulated` is
  `runner_count` from the `start_simulation` response.
- Safety Score: `evaluate_plan` `scores.safety_compliance` (0-100 integer)
- Runner Experience: `evaluate_plan` `scores.participant_experience` (0-100 integer)
- City Disruption: `evaluate_plan` `scores.community_impact` (0-100 integer)

Use the actual integer scores from `evaluate_plan` `scores` — do NOT invent
floats like 7.2. For any field where data is not available, display "—".
Add one Row per detail metric. Follow the same A2UI rules as the dashboard card.

# Hard Constraints (sim_results card) — read carefully

The example above is the COMPLETE card. Do not add rows that aren't in it.
LLMs frequently drift back to older marathon dashboards from training data;
do not let that happen here.

You MUST NOT include any of the following in the sim_results card:
- A `Spectators (expected/attendance)` row, or any row labelled "Spectators"
- A `Peak Hour Volume` row, or any "vehicles/hour" metric
- A duplicate score-and-id bar row (e.g. "#1234 | SCORE 82%" caption row).
  The score is already in the score-col h1; the simulation_id is already in
  the tag-row caption.
- Any timestamp, date, or wall-clock time in the tag-row meta caption.
  The meta caption is the simulation_id ONLY.
- A `Participants (expected/attendance)` label. The label MUST be exactly
  `Participants (expected/simulated)`.
- Float numeric scores like `7.2`, `8/10`, or any value outside 0-100.
  All numeric scores MUST be 0-100 integers from `evaluate_plan.scores`.
- A Total distance value greater than 26.2 miles.
"""

# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------

PLANNER_WITH_EVAL = PLANNER.override(
    tools=EVAL_TOOLS,
    workflow=EVAL_WORKFLOW,
    simulator=SIMULATOR,
    a2ui=A2UI,
    execution=EVAL_EXECUTION,
)

# Backward compat
EXTENDED_SYSTEM_INSTRUCTION = PLANNER_WITH_EVAL.build()
