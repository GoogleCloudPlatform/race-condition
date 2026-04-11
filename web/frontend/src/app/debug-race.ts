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

const MARATHON_DISTANCE_MI = 26.2;
const MIN_VELOCITY = 0.6;
const MAX_VELOCITY = 1.4;
const WATER_DEPLETION_PER_MILE = 2.414;
const REHYDRATE_AMOUNT = 30;
const REHYDRATE_THRESHOLD = 60;
const EXHAUSTION_THRESHOLD = 30;
const EXHAUSTION_SPEED_FACTOR = 0.5;
const TICK_INTERVAL_MS = 3000;
const SIM_DISTANCE_INTEGRATOR = 0.05;

interface RunnerState {
  id: string;
  guid: string;
  velocity: number;
  water: number;
  distanceMi: number;
  finished: boolean;
}

let _states: RunnerState[] = [];
let _tickTimer: ReturnType<typeof setInterval> | null = null;
let _running = false;
let _speedMultiplier = 1;

function uid(): string {
  return 'dbg-' + Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 6);
}

function dispatch(type: string, detail?: any): void {
  window.dispatchEvent(new CustomEvent(type, detail !== undefined ? { detail } : undefined));
}

export function startDebugRace(count: number, speed = 1): void {
  stopDebugRace();
  _states = [];
  _running = true;
  _speedMultiplier = speed;

  for (let i = 0; i < count; i++) {
    const id = uid();
    _states.push({
      id,
      guid: `sim-${id}`,
      velocity: MIN_VELOCITY + Math.random() * (MAX_VELOCITY - MIN_VELOCITY),
      water: 100,
      distanceMi: 0,
      finished: false,
    });
  }

  emulateSpawnAndStart();
}

function emulateSpawnAndStart(): void {
  for (const s of _states) {
    dispatch('hud:addSimRunner', {
      guid: s.guid,
      velocity: 0,
      distanceMi: 0,
      progress: 0,
    });
  }

  setTimeout(() => {
    if (!_running) return;
    for (const s of _states) {
      dispatch('hud:updateSimRunner', {
        guid: s.guid,
        velocity: s.velocity,
        water: s.water,
        _fromGateway: true,
      });
    }
    _tickTimer = setInterval(tick, TICK_INTERVAL_MS);
  }, 500);

  setTimeout(() => {
    if (!_running) return;
    dispatch('sim:raceStarted', {
      speedMultiplier: _speedMultiplier,
      simDistanceIntegrator: SIM_DISTANCE_INTEGRATOR,
      _debugRace: true,
    });
  }, 1500);
}

function tick(): void {
  if (!_running) return;
  const dt = TICK_INTERVAL_MS / 1000;

  for (const s of _states) {
    if (s.finished) continue;

    const prevDist = s.distanceMi;
    s.distanceMi = Math.min(
      MARATHON_DISTANCE_MI,
      s.distanceMi + s.velocity * dt * 0.112 * _speedMultiplier,
    );

    s.water = Math.max(0, s.water - (s.distanceMi - prevDist) * WATER_DEPLETION_PER_MILE);

    const prevMile = Math.floor(prevDist);
    const newMile = Math.floor(s.distanceMi);
    for (let mi = prevMile + 1; mi <= newMile; mi++) {
      if (mi % 3 === 0 && s.water < REHYDRATE_THRESHOLD) {
        s.water = Math.min(100, s.water + REHYDRATE_AMOUNT);
        dispatch('sim:runnerEvent', { guid: s.guid, event: 'water_station' });
      }
    }

    if (s.water < EXHAUSTION_THRESHOLD) {
      s.velocity = Math.max(0.2, s.velocity * EXHAUSTION_SPEED_FACTOR);
      dispatch('sim:runnerEvent', { guid: s.guid, event: 'exhausted' });
    }

    dispatch('hud:updateSimRunner', {
      guid: s.guid,
      velocity: s.velocity,
      water: s.water,
      _fromGateway: true,
    });

    if (s.distanceMi >= MARATHON_DISTANCE_MI) {
      s.finished = true;
      s.velocity = 0;
    }
  }

  if (_states.every((s) => s.finished)) {
    dispatch('sim:finished');
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
