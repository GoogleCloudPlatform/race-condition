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
import { Runner } from './runner';
import { agentGateway } from './agent-gateway-updates';

interface BufferedEvent {
  guid: string;
  event: string;
  text: string;
  water?: number;
}

export interface RunnerInfo {
  guid: string;
  velocity: number;
  percentComplete: number;
  status: 'running' | 'finished' | 'did-not-finish';
}

export class RunnerManager {
  private runners = new Map<string, Runner>();
  private scene: THREE.Scene;
  simSpeed = 1.0;

  // Sim runner event buffering
  simTargetGuid: string | null = null;
  private simEventBuffer: BufferedEvent[] = [];
  private simFlushTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
  }

  addRunnerWithGuid(
    guid: string,
    path: IMapPath,
    params: { effectiveMph: number; simDistanceIntegrator: number; distanceMi?: number },
    color = '#ffffff',
    opts?: { mesh?: THREE.Mesh; sidewaysOffset?: number },
  ): void {
    if (this.runners.has(guid)) return;
    const broadcastFn =
      guid.startsWith('sim-') && this.simTargetGuid
        ? (g: string, text: string) => this.bufferSimEvent(g, text)
        : undefined;
    const runner = new Runner(guid, {
      scene: this.scene,
      path,
      effectiveMph: params.effectiveMph,
      simDistanceIntegrator: params.simDistanceIntegrator,
      distanceMi: params.distanceMi,
      color,
      broadcastFn,
      mesh: opts?.mesh,
      sidewaysOffset: opts?.sidewaysOffset,
    });
    this.runners.set(guid, runner);
  }

  getRunnerColor(guid: string): string | null {
    return this.runners.get(guid)?.color ?? null;
  }

  removeRunner(guid: string): void {
    const runner = this.runners.get(guid);
    if (runner) {
      runner.dispose();
      this.runners.delete(guid);
    }
  }

  /**
   * Resolve a runner by guid, trying both the raw guid and the sim-prefixed variant.
   * This handles the case where the gateway sends raw session IDs but runners
   * are stored with a `sim-` prefix.
   */
  private resolve(guid: string): Runner | undefined {
    return this.runners.get(guid) ?? this.runners.get(`sim-${guid}`);
  }

  getRunner(guid: string): Runner | undefined {
    return this.resolve(guid);
  }

  /** Normalized velocity (backend `effective_velocity` scale). */
  setVelocity(guid: string, velocity: number): void {
    this.resolve(guid)?.setVelocity(velocity);
  }

  setSimDistanceIntegrator(guid: string, factor: number): void {
    this.resolve(guid)?.setSimDistanceIntegrator(factor);
  }

  setWater(guid: string, water: number): void {
    this.resolve(guid)?.setWater(water);
  }

  /** Set runner position directly as normalized 0-1 progress. */
  setProgress(guid: string, t: number): void {
    this.resolve(guid)?.setProgress(t);
  }

  /** Sync runner toward backend-reported progress with smooth interpolation. */
  syncBackendProgress(guid: string, progress: number, velocity: number): void {
    const runner = this.resolve(guid);
    if (!runner) return;
    const pathLength = runner.getPathLength();
    const progressRate = pathLength > 0 ? velocity / pathLength : 0;
    runner.syncFromBackend(progress, progressRate);
  }

  /** Mark a runner as collapsed/DNF. */
  setCollapsed(guid: string): void {
    this.resolve(guid)?.setCollapsed();
  }

  setWorking(guid: string, working: boolean): void {
    // If the guid is the sim target agent, pause/resume all sim runners
    if (guid === this.simTargetGuid) {
      for (const [id, runner] of this.runners) {
        if (id.startsWith('sim-')) runner.working = working;
      }
      return;
    }
    const runner = this.runners.get(guid);
    if (runner) runner.working = working;
  }

  getRunnerWater(guid: string): number {
    return this.runners.get(guid)?.getWater() ?? 100;
  }

  getRunnerWaterLevels(): Map<string, number> {
    const map = new Map<string, number>();
    for (const [guid, runner] of this.runners) {
      map.set(guid, runner.getWater());
    }
    return map;
  }

  tick(deltaSeconds: number): void {
    const scaled = deltaSeconds * this.simSpeed;
    for (const runner of this.runners.values()) {
      runner.tick(scaled);
    }
  }

  getRunnerInfos(): RunnerInfo[] {
    return Array.from(this.runners.values()).map((r) => ({
      guid: r.guid,
      velocity: r.getVelocity(),
      percentComplete: r.getT() * 100,
      status: r.status,
    }));
  }

  getRunnerPosition(guid: string): THREE.Vector3 | null {
    return this.runners.get(guid)?.getPosition() ?? null;
  }

  getRunnerPositions(): Map<string, THREE.Vector3> {
    const map = new Map<string, THREE.Vector3>();
    for (const [guid, runner] of this.runners) {
      map.set(guid, runner.getPosition());
    }
    return map;
  }

  hasRunners(): boolean {
    return this.runners.size > 0;
  }

  getRunners(): Map<string, Runner> {
    return this.runners;
  }

  private bufferSimEvent(guid: string, text: string): void {
    try {
      const parsed = JSON.parse(text);
      this.simEventBuffer.push({
        guid,
        event: parsed.event ?? 'unknown',
        text: parsed.text ?? text,
        water: parsed.water,
      });
    } catch {
      this.simEventBuffer.push({ guid, event: 'unknown', text, water: undefined });
    }
    if (!this.simFlushTimer) {
      this.simFlushTimer = setTimeout(() => this.flushSimEvents(), 1000);
    }
  }

  private flushSimEvents(): void {
    this.simFlushTimer = null;
    if (!this.simTargetGuid || this.simEventBuffer.length === 0) return;
    if (agentGateway.isNdjsonReplayActive()) {
      this.simEventBuffer.length = 0;
      return;
    }

    const events = this.simEventBuffer.splice(0);
    // Group by event type
    const groups = new Map<string, BufferedEvent[]>();
    for (const e of events) {
      const list = groups.get(e.event) ?? [];
      list.push(e);
      groups.set(e.event, list);
    }

    const lines: string[] = [];
    for (const [eventType, items] of groups) {
      const names = items.map((e) => e.guid.replace('sim-', 'Runner ')).join(', ');
      if (eventType === 'milestone') {
        lines.push(`${names}: ${items[0].text}`);
      } else if (eventType === 'water_station') {
        lines.push(
          `${names} entered a water station (water levels: ${items.map((e) => `${e.guid.replace('sim-', 'Runner ')}: ${e.water ?? '?'}%`).join(', ')})`,
        );
      } else if (eventType === 'medical_tent') {
        lines.push(
          `${names} entered a medical tent area (water levels: ${items.map((e) => `${e.guid.replace('sim-', 'Runner ')}: ${e.water ?? '?'}%`).join(', ')})`,
        );
      } else if (eventType === 'finish') {
        lines.push(`${names} crossed the finish line!`);
      } else {
        lines.push(`${names}: ${items[0].text}`);
      }
    }

    agentGateway.sendBroadcast(JSON.stringify({ events: lines }), [this.simTargetGuid]);
  }

  dispose(): void {
    if (this.simFlushTimer) clearTimeout(this.simFlushTimer);
    for (const runner of this.runners.values()) runner.dispose();
    this.runners.clear();
  }
}
