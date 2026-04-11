/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Marathon simulation constants aligned with backend/agents/npc/runner_shared/constants.py
 */
export const RUNNER_SPEED_SCALE = 6.2137;
/** Official marathon distance in miles (matches backend MARATHON_MI). */
export const MARATHON_DISTANCE_MI = 26.2188;
/**
 * Default simulated-time compression for the viewport race clock.
 * Must match ViewportComponent.SIM_SPEED; overridden per-race via setSimDistanceIntegrator.
 */
export const RUNNER_DEFAULT_SIM_SPEED = 360;

/**
 * Hardcoded race tick grid for wall-clock distance integration (no prepare_simulation payload).
 * HARDCODED_SIM_TOTAL_RACE_HOURS is simulated marathon clock span (not wall-clock UI duration).
 */
export const HARDCODED_SIM_MAX_TICKS = 12;
export const HARDCODED_SIM_TICK_INTERVAL_SEC = 10;
export const HARDCODED_SIM_TOTAL_RACE_HOURS = 6;

/** Wall-clock duration for the agent-screen simulation progress bar (linear 0–100%). */
export const HARDCODED_SIM_PROGRESS_WALL_MS =
  HARDCODED_SIM_MAX_TICKS * HARDCODED_SIM_TICK_INTERVAL_SEC * 1000;

/** Simulated hours per real second: (sim_hours / ticks) / seconds_per_tick wall. */
export const HARDCODED_SIM_DISTANCE_INTEGRATOR =
  HARDCODED_SIM_TOTAL_RACE_HOURS / HARDCODED_SIM_MAX_TICKS / HARDCODED_SIM_TICK_INTERVAL_SEC;
