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

import * as THREE from 'three';
import { IMapPath } from './path';
import { StationZone } from './water-station';
import { agentGateway } from './agent-gateway-updates';
import { simLog } from './sim-logger';
import {
  MARATHON_DISTANCE_MI,
  RUNNER_DEFAULT_SIM_SPEED,
  RUNNER_SPEED_SCALE,
} from './runner-sim-constants';
import {
  DNF_RUNNER_EMOJIS,
  EXAMPLE_DNF_RUNNER_THOUGHTS,
  EXAMPLE_LOW_VITAL_RUNNER_THOUGHTS,
  EXAMPLE_RUNNER_THOUGHTS,
  LOW_VITALS_EMOJIS,
  RUNNER_EMOJIS,
} from '../constants';

const _perpScratch = new THREE.Vector3();
const _lookScratch = new THREE.Vector3();

export interface RunnerConfig {
  scene: THREE.Scene;
  path: IMapPath;
  /** Effective speed in mph (backend: normalized_velocity * RUNNER_SPEED_SCALE). */
  effectiveMph: number;
  /** Real mph × this × Δt seconds = Δ miles; matches viewport simSpeedMultiplier. */
  simDistanceIntegrator: number;
  /** Optional starting distance in miles (e.g. from backend). */
  distanceMi?: number;
  color?: string;
  broadcastFn?: (guid: string, text: string) => void;
  /** Optional pre-created mesh (e.g. lookdev icosahedron). When provided the Runner manages it instead of creating a default dot. */
  mesh?: THREE.Mesh;
  /** Override for the perpendicular sideways offset. Defaults to small jitter for dot meshes. */
  sidewaysOffset?: number;
}

export type RunnerStatus = 'running' | 'finished' | 'did-not-finish';

export class Runner {
  readonly guid: string;
  status: RunnerStatus = 'running';

  private path: IMapPath;
  private t = 0;
  private totalLength: number;
  /** Miles per hour (matches backend effective_mph). */
  private effectiveMph = 0;
  /** Factor: Δmi = effectiveMph × simDistanceIntegrator × Δt_real (see viewport simSpeedMultiplier). */
  private simDistanceIntegrator = RUNNER_DEFAULT_SIM_SPEED / 3600;
  /** Authoritative race distance in miles; progress t = distanceMi / MARATHON_DISTANCE_MI. */
  private distanceMi = 0;
  private rawMph = 0;
  private sidewaysOffset: number;

  private dnfEmoji: string;
  private emoji: string;
  private lowVitalEmoji: string;

  private dnfThought: string;
  private lowVitalThought: string;
  private thought: string;

  readonly color: string;
  water = 100;
  working = false;

  private insideStations = new Set<number>();
  private lastMilestoneMi = 0;
  private broadcastFn?: (guid: string, text: string) => void;

  // Backend sync state (exponential blend toward backend-reported progress)
  private _backendProgress: number | undefined;
  private _backendProgressRate = 0;
  private _backendProgressSetAt: number | undefined;

  private dot: THREE.Mesh;
  private scene: THREE.Scene;
  /** True when the Runner created its own dot mesh; false when an external mesh was injected. */
  private ownsMesh: boolean;

  private static geo = new THREE.CircleGeometry(0.7, 8);
  /** First runner created — used for focused debug logging. */
  static trackedGuid: string | null = null;

  static {
    Runner.geo.rotateX(-Math.PI / 2);
  }

  private get _isTracked(): boolean {
    return this.guid === Runner.trackedGuid;
  }

  constructor(guid: string, config: RunnerConfig) {
    this.guid = guid;
    if (!Runner.trackedGuid) {
      Runner.trackedGuid = guid;
      const rawId = guid.startsWith('sim-') ? guid.slice(4) : guid;
    }
    this.color = config.color ?? '#ffffff';
    this.path = config.path;
    this.effectiveMph = Math.max(0, config.effectiveMph);
    this.simDistanceIntegrator = config.simDistanceIntegrator;
    this.distanceMi = Math.min(MARATHON_DISTANCE_MI, Math.max(0, config.distanceMi ?? 0));
    this.t = MARATHON_DISTANCE_MI > 0 ? this.distanceMi / MARATHON_DISTANCE_MI : 0;
    this.rawMph = this.effectiveMph;
    this.totalLength = config.path.getTotalLength();
    this.scene = config.scene;
    this.broadcastFn = config.broadcastFn;

    this.emoji = RUNNER_EMOJIS[Math.floor(Math.random() * RUNNER_EMOJIS.length)];
    this.dnfEmoji = DNF_RUNNER_EMOJIS[Math.floor(Math.random() * DNF_RUNNER_EMOJIS.length)];
    this.lowVitalEmoji = LOW_VITALS_EMOJIS[Math.floor(Math.random() * LOW_VITALS_EMOJIS.length)];

    this.dnfThought =
      EXAMPLE_DNF_RUNNER_THOUGHTS[Math.floor(Math.random() * EXAMPLE_DNF_RUNNER_THOUGHTS.length)];
    this.lowVitalThought =
      EXAMPLE_LOW_VITAL_RUNNER_THOUGHTS[
        Math.floor(Math.random() * EXAMPLE_LOW_VITAL_RUNNER_THOUGHTS.length)
      ];
    this.thought =
      EXAMPLE_RUNNER_THOUGHTS[Math.floor(Math.random() * EXAMPLE_RUNNER_THOUGHTS.length)];

    if (config.mesh) {
      this.dot = config.mesh;
      this.ownsMesh = false;
      this.sidewaysOffset = config.sidewaysOffset ?? (Math.random() - 0.5) * 15;
    } else {
      const mat = new THREE.MeshBasicMaterial({ color: this.color, depthTest: false });
      this.dot = new THREE.Mesh(Runner.geo, mat);
      this.dot.renderOrder = 15;
      this.scene.add(this.dot);
      this.ownsMesh = true;
      this.sidewaysOffset = config.sidewaysOffset ?? (Math.random() - 0.5) * 0.6;
    }

    this.updateDotPosition();
  }

  tick(deltaSeconds: number): void {
    if (this.status !== 'running' || this.working) return;

    // Same physics as backend process_tick: Δmi = (effective_mph / 60) × Δsim_min,
    // with Δsim_min implied by viewport time compression (simDistanceIntegrator × Δt_real).
    const deltaMi = this.effectiveMph * this.simDistanceIntegrator * deltaSeconds;
    this.distanceMi = Math.min(MARATHON_DISTANCE_MI, this.distanceMi + deltaMi);
    this.t = MARATHON_DISTANCE_MI > 0 ? this.distanceMi / MARATHON_DISTANCE_MI : 0;

    // Do NOT auto-promote to 'finished' here.  Only the backend has
    // authority to determine finish status.  The runner visually reaches
    // t=1.0 but keeps status 'running' until the backend confirms via
    // setCollapsed(), freeze(), or setProgress().

    this.checkDistanceMilestone();
    this.checkStations();
  }

  private checkDistanceMilestone(): void {
    const rawGuid = this.guid.startsWith('sim-') ? this.guid.slice(4) : this.guid;
    const interval = 3;
    while (this.distanceMi >= this.lastMilestoneMi + interval) {
      this.lastMilestoneMi += interval;
      const mile = Math.round(this.lastMilestoneMi);
      const msg = JSON.stringify({
        event: 'milestone',
        text: `Completed mile ${mile} (${Math.round(this.t * 100)}% done)`,
        water: this.water,
      });
      if (!agentGateway.isNdjsonReplayActive()) {
        if (this.broadcastFn) {
          this.broadcastFn(this.guid, msg);
        } else {
          agentGateway.sendBroadcast(msg, [rawGuid], true);
        }
      }
    }
  }

  setWater(value: number): void {
    const prev = this.water;
    this.water = Math.max(0, Math.min(100, value));
    if (this._isTracked && Math.abs(this.water - prev) > 0.1) {
    }
  }

  getWater(): number {
    return Math.round(this.water * 100) / 100;
  }

  private checkStations(): void {
    const pos = this.getPosition();
    for (const station of this.path.allStations) {
      const inside = station.isInsideRadius(pos);
      const wasInside = this.insideStations.has(station.id);
      if (inside && !wasInside) {
        this.insideStations.add(station.id);
        this.onEnterStation(station);
      } else if (!inside && wasInside) {
        this.insideStations.delete(station.id);
      }
    }
  }

  private onEnterStation(station: StationZone): void {
    const rawGuid = this.guid.startsWith('sim-') ? this.guid.slice(4) : this.guid;
    let eventPayload: Record<string, unknown>;
    let logMessage: string;
    switch (station.stationType) {
      case 'water_station':
        eventPayload = { event: 'hydration_station' };
        logMessage = 'Entered water station';
        break;
      case 'crowd_zone':
        eventPayload = { event: 'crowd_boost', intensity: 0.8 };
        logMessage = 'Entered crowd zone';
        break;
      default:
        eventPayload = { event: 'medical_tent' };
        logMessage = 'Entered medical tent';
        break;
    }
    const msg = JSON.stringify(eventPayload);
    simLog.log(
      'STATION',
      this.guid,
      `${station.stationType} #${station.id} water=${this.water.toFixed(1)}`,
    );
    if (this._isTracked) {
    }
    if (!agentGateway.isNdjsonReplayActive()) {
      // Crowd zones: no gateway broadcast (ambient only). Other stations: notify backend process_tick.
      if (station.stationType !== 'crowd_zone') {
        agentGateway.sendBroadcast(msg, [rawGuid], true);
      }
      if (this.broadcastFn) {
        this.broadcastFn(this.guid, msg);
      }
    }
    // Emit to HUD event log
    window.dispatchEvent(
      new CustomEvent('sim:eventLog', {
        detail: {
          guid: this.guid,
          type: 'station',
          message: logMessage,
          time: Date.now(),
        },
      }),
    );
  }

  /** Store the backend's authoritative progress so tick() blends toward it. */
  syncFromBackend(progress: number, progressRate: number): void {
    if (this._isTracked) {
      const mi = (progress * 26.2).toFixed(1);
    }
    this._backendProgress = progress;
    this._backendProgressRate = progressRate;
    this._backendProgressSetAt = performance.now();
  }

  getLastSyncTime(): number | undefined {
    return this._backendProgressSetAt;
  }

  /**
   * Set normalized runner speed (same units as backend `effective_velocity`).
   * Used by JSON commands and gateway updates.
   */
  setVelocity(normalized: number): void {
    this.effectiveMph = Math.max(0, normalized * RUNNER_SPEED_SCALE);
    this.rawMph = this.effectiveMph;
  }

  setRawMph(mph: number): void {
    this.rawMph = mph;
  }

  /** Immediately halt the runner in place (e.g. when the simulation ends). */
  freeze(asDnf = false): void {
    if (asDnf) {
      this.status = 'did-not-finish';
    } else if (this.status !== 'did-not-finish') {
      this.status = 'finished';
    }
    this.effectiveMph = 0;
    this._backendProgress = undefined;
    this._backendProgressRate = 0;
    this._backendProgressSetAt = undefined;
  }

  /** Set position directly as normalized 0-1 progress along path. */
  setProgress(t: number): void {
    if (isNaN(t)) return;
    this.t = Math.max(0, Math.min(1, t));
    this.distanceMi = this.t * MARATHON_DISTANCE_MI;
    const milestoneFloor = Math.floor(this.distanceMi / 3) * 3;
    this.lastMilestoneMi = Math.min(this.lastMilestoneMi, milestoneFloor);
    // Do NOT auto-promote to 'finished' — only backend has authority.
  }

  /** Mark runner as collapsed (DNF). */
  setCollapsed(): void {
    this.status = 'did-not-finish';
    this.effectiveMph = 0;
  }

  /** Normalized velocity (matches backend `effective_velocity` scale). */
  getVelocity(): number {
    return RUNNER_SPEED_SCALE > 0 ? this.effectiveMph / RUNNER_SPEED_SCALE : 0;
  }

  setSimDistanceIntegrator(factor: number): void {
    if (factor >= 0 && Number.isFinite(factor)) {
      this.simDistanceIntegrator = factor;
    }
  }

  getT(): number {
    return this.t;
  }

  getPace(): string {
    if (this.rawMph <= 0) return '--:--';
    const totalMinutes = 60 / this.rawMph;
    const mins = Math.floor(totalMinutes);
    const secs = Math.round((totalMinutes % 1) * 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  getEmoji(): string {
    return this.status === 'did-not-finish'
      ? this.dnfEmoji
      : this.getWater() < 30
        ? this.lowVitalEmoji
        : this.emoji;
  }

  getThought(): string {
    return this.status === 'did-not-finish'
      ? this.dnfThought
      : this.getWater() < 30
        ? this.lowVitalThought
        : this.thought;
  }

  /**
   * Returns the 1-based finishing position of this runner among all provided runners.
   * Runners with a higher `t` value (further along the course) rank ahead.
   * DNF runners are sorted behind all still-running runners regardless of distance covered.
   */
  getPlace(allRunners: Runner[]): number {
    const thisDnf = this.status === 'did-not-finish';
    return (
      allRunners.filter((other) => {
        if (other === this) return false;
        const otherDnf = other.status === 'did-not-finish';
        if (thisDnf || otherDnf) console.log('was a dnf !!');
        if (thisDnf !== otherDnf) return !thisDnf ? false : true; // DNF always loses to non-DNF
        return other.t > this.t;
      }).length + 1
    );
  }

  getPathLength(): number {
    return this.totalLength;
  }

  getPosition(): THREE.Vector3 {
    return this.path.getPositionAt(this.t);
  }

  /** Access the underlying THREE.Mesh for visual effects (e.g. color flashing). */
  getMesh(): THREE.Mesh {
    return this.dot;
  }

  /** Set the mesh color, handling both MeshBasicMaterial (dot) and MeshStandardMaterial (custom). */
  private setMeshColor(color: number): void {
    if (this.ownsMesh) {
      (this.dot.material as THREE.MeshBasicMaterial).color.set(color);
    } else {
      (this.dot.material as THREE.MeshStandardMaterial).emissive.set(color);
    }
  }

  private updateDotPosition(): void {
    const pos = this.path.getPositionAt(this.t);
    const tangent = this.path.getTangentAt(this.t);
    _perpScratch.set(-tangent.z, 0, tangent.x).normalize();

    if (this.ownsMesh) {
      this.dot.position.set(
        pos.x + _perpScratch.x * this.sidewaysOffset,
        0.3,
        pos.z + _perpScratch.z * this.sidewaysOffset,
      );
    } else {
      // Custom mesh: keep path Y and orient along tangent
      this.dot.position.set(
        pos.x + _perpScratch.x * this.sidewaysOffset,
        pos.y,
        pos.z + _perpScratch.z * this.sidewaysOffset,
      );
      _lookScratch.copy(this.dot.position).addScaledVector(tangent, 10);
      this.dot.lookAt(_lookScratch);
    }
  }

  dispose(): void {
    this.scene.remove(this.dot);
    if (this.ownsMesh) {
      (this.dot.material as THREE.MeshBasicMaterial).dispose();
    } else {
      this.dot.geometry?.dispose();
      (this.dot.material as THREE.Material)?.dispose();
    }
  }
}
