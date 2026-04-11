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

export const DEBUG_RUNNER_MIN_VELOCITY = 0.6;
export const DEBUG_RUNNER_MAX_VELOCITY = 1.4;
export const DEBUG_RUNNER_DEPLETION_PER_MILE = 2.414;
export const DEBUG_RUNNER_REHYDRATE_AMOUNT = 30;
export const DEBUG_RUNNER_REHYDRATE_THRESHOLD = 60;
export const DEBUG_RUNNER_EXHAUSTION_THRESHOLD = 30;
export const DEBUG_RUNNER_EXHAUSTION_SPEED_FACTOR = 0.5;
export const DEBUG_RUNNER_TICK_INTERVAL = 3000;
const MARATHON_DISTANCE_MI = 26.2;

interface EmulatedBackendState {
  guid: string;
  velocity: number;
  water: number;
  distanceMi: number;
}

let _states: EmulatedBackendState[] = [];
let _tickTimer: ReturnType<typeof setInterval> | null = null;
let _tickCount = 0;
let _running = false;
let _speedMultiplier = 1;

function uid(): string {
  return 'dbg-' + Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 6);
}

export function startDebugRace(count: number, speed = 1): void {
  stopDebugRace();
  _states = [];
  _tickCount = 0;
  _running = true;
  _speedMultiplier = speed;

  window.dispatchEvent(new CustomEvent('sim:raceStarted', { detail: { speedMultiplier: _speedMultiplier } }));

  for (let i = 0; i < count; i++) {
    const guid = `sim-${uid()}`;
    const velocity = DEBUG_RUNNER_MIN_VELOCITY + Math.random() * (DEBUG_RUNNER_MAX_VELOCITY - DEBUG_RUNNER_MIN_VELOCITY);
    _states.push({ guid, velocity, water: 100, distanceMi: 0 });

    window.dispatchEvent(new CustomEvent('hud:addSimRunner', {
      detail: { guid, color: '#FFFFFF', velocity, distanceMi: 0, progress: 0 },
    }));
  }
  _tickTimer = setInterval(() => tick(), DEBUG_RUNNER_TICK_INTERVAL);
}

function tick(): void {
  if (!_running) return;
  const dtSeconds = DEBUG_RUNNER_TICK_INTERVAL / 1000;

  for (const s of _states) {
    if (s.distanceMi >= MARATHON_DISTANCE_MI) continue;

    const prevDist = s.distanceMi;
    s.distanceMi = Math.min(MARATHON_DISTANCE_MI, s.distanceMi + s.velocity * dtSeconds * 0.112 * _speedMultiplier);

    s.water = Math.max(0, s.water - (s.distanceMi - prevDist) * DEBUG_RUNNER_DEPLETION_PER_MILE);

    const prevMile = Math.floor(prevDist);
    const newMile = Math.floor(s.distanceMi);
    for (let mi = prevMile + 1; mi <= newMile; mi++) {
      if (mi % 3 === 0 && s.water < DEBUG_RUNNER_REHYDRATE_THRESHOLD) {
        s.water = Math.min(100, s.water + DEBUG_RUNNER_REHYDRATE_AMOUNT);
      }
    }

    if (s.water < DEBUG_RUNNER_EXHAUSTION_THRESHOLD) {
      s.velocity = Math.max(0.2, s.velocity * DEBUG_RUNNER_EXHAUSTION_SPEED_FACTOR);
    }

    window.dispatchEvent(new CustomEvent('hud:updateSimRunner', {
      detail: {
        guid: s.guid,
        velocity: s.velocity,
        water: s.water,
        distanceMi: s.distanceMi,
        progress: s.distanceMi / MARATHON_DISTANCE_MI,
      },
    }));

    if (s.distanceMi >= MARATHON_DISTANCE_MI) {
      s.velocity = 0;
    }
  }

  _tickCount++;
  const active = _states.filter(s => s.distanceMi < MARATHON_DISTANCE_MI);
  const all = _states;
  const avgVel = all.reduce((sum, s) => sum + s.velocity, 0) / all.length;
  const avgWater = all.reduce((sum, s) => sum + s.water, 0) / all.length;
  const avgDist = all.reduce((sum, s) => sum + s.distanceMi, 0) / all.length;
  const realTimeMins = (_tickCount * DEBUG_RUNNER_TICK_INTERVAL / 1000) * 180 / 60;

  window.dispatchEvent(new CustomEvent('sim:tickUpdate', {
    detail: {
      avg_velocity: Math.round(avgVel * 100) / 100,
      avg_water: Math.round(avgWater * 10) / 10,
      avg_distance: Math.round(avgDist * 100) / 100,
      real_time_minutes: Math.round(realTimeMins),
      runners_reporting: active.length,
      tick: Math.round(avgDist / MARATHON_DISTANCE_MI * 100),
      max_ticks: 100,
    },
  }));

  if (_states.every(s => s.distanceMi >= MARATHON_DISTANCE_MI)) {
    window.dispatchEvent(new CustomEvent('sim:finished'));
    stopDebugRace();
  }
}

export function stopDebugRace(): void {
  _running = false;
  if (_tickTimer) {
    clearInterval(_tickTimer);
    _tickTimer = null;
  }
  _states = [];
}

export function isDebugRaceRunning(): boolean {
  return _running;
}
