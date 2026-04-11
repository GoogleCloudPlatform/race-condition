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

/** Measurable sections of the animate() loop. */
export const PERF_SECTIONS = [
  'runnerTick',
  'runnerPosition',
  'zoneCheck',
  'raycast',
  'depthPrePass',
  'composerRender',
] as const;

export type PerfSection = (typeof PERF_SECTIONS)[number];

export interface PerfTimingEntry {
  avg: number;
  p95: number;
}

export interface PerfStatEntry {
  min: number;
  avg: number;
  max: number;
  p50: number;
  p95: number;
  p99: number;
}

/** JSON snapshot emitted after a timed capture completes. */
export interface PerfSnapshot {
  timestamp: string;
  durationMs: number;
  frames: number;
  conditions: {
    runners: number;
    camera: 'static' | 'follow-leader';
    source: 'debug-race' | 'backend';
  };
  fps: PerfStatEntry;
  frameTimeMs: PerfStatEntry;
  drawCalls: { min: number; avg: number; max: number };
  triangles: number;
  textures: number;
  geometries: number;
  timing: Record<PerfSection | 'jsTotal' | 'gpuInferred', PerfTimingEntry>;
  label: string;
}

const RING_CAPACITY = 300;

/** All timing keys used for per-section tracking (PERF_SECTIONS + derived). */
const ALL_TIMING_KEYS: readonly string[] = [...PERF_SECTIONS, 'jsTotal', 'gpuInferred'];

function percentile(sorted: Float64Array | number[], p: number): number {
  const len = sorted.length;
  if (len === 0) return 0;
  const i = Math.max(0, Math.ceil((p / 100) * len) - 1);
  return sorted[i];
}

/**
 * Collects per-frame performance data from the Three.js renderer and exposes
 * rolling averages. Supports a timed sampling capture that logs a JSON snapshot
 * to the console.
 *
 * Only instantiate when `?debug=true`.
 */
export class PerfMonitor {
  // ── Ring buffers ──────────────────────────────────────────────────────────
  private readonly _deltas = new Float64Array(RING_CAPACITY);
  private readonly _drawCalls = new Float64Array(RING_CAPACITY);
  private readonly _triangles = new Float64Array(RING_CAPACITY);
  private _head = 0;
  private _count = 0;

  // ── Per-section ring buffers ──────────────────────────────────────────────
  private readonly _sectionBuffers = new Map<string, Float64Array>();
  private readonly _sectionHeads = new Map<string, number>();

  // ── Live properties (rolling averages) ────────────────────────────────────
  fps = 0;
  frameTimeMs = 0;
  drawCalls = 0;
  triangles = 0;
  textures = 0;
  geometries = 0;

  // ── Sampling state ────────────────────────────────────────────────────────
  private _sampling = false;
  private _sampleStart = 0;
  private _sampleDuration = 0;
  private _sampleLabel = '';
  private _sampleRunners = 0;
  private _sampleCamera: 'static' | 'follow-leader' = 'static';
  private _sampleSource: 'debug-race' | 'backend' = 'debug-race';
  private _sampleOnComplete?: (snapshot: PerfSnapshot) => void;

  private _sampleFrames = 0;
  private _sampleFpsMin = Infinity;
  private _sampleFpsMax = -Infinity;
  private _sampleFpsSum = 0;
  private _sampleFtMin = Infinity;
  private _sampleFtMax = -Infinity;
  private _sampleFtSum = 0;
  private _sampleDcMin = Infinity;
  private _sampleDcMax = -Infinity;
  private _sampleDcSum = 0;

  // ── Per-sample value accumulators ─────────────────────────────────────────
  private _sampleSectionValues = new Map<string, number[]>();
  private _sampleFtValues: number[] = [];
  private _sampleFpsValues: number[] = [];

  constructor() {
    for (const section of PERF_SECTIONS) {
      this._sectionBuffers.set(section, new Float64Array(RING_CAPACITY));
      this._sectionHeads.set(section, 0);
    }
    // Also track jsTotal and gpuInferred
    this._sectionBuffers.set('jsTotal', new Float64Array(RING_CAPACITY));
    this._sectionHeads.set('jsTotal', 0);
    this._sectionBuffers.set('gpuInferred', new Float64Array(RING_CAPACITY));
    this._sectionHeads.set('gpuInferred', 0);
  }

  get isSampling(): boolean {
    return this._sampling;
  }

  /**
   * Call once per frame, after rendering but before the next rAF.
   *
   * @param delta Frame delta in **seconds** (from THREE.Clock / Timer).
   * @param renderer The WebGLRenderer whose `.info` stats are read.
   */
  tick(delta: number, renderer: THREE.WebGLRenderer): void {
    const ft = delta * 1000; // frame time in ms
    const currentFps = delta > 0 ? 1 / delta : 0;
    const info = renderer.info;
    const dc = info.render.calls;
    const tri = info.render.triangles;

    // Write into ring buffers
    const idx = this._head % RING_CAPACITY;
    this._deltas[idx] = ft;
    this._drawCalls[idx] = dc;
    this._triangles[idx] = tri;
    this._head++;
    if (this._count < RING_CAPACITY) this._count++;

    // Compute rolling averages over the filled portion of the ring
    let sumFt = 0;
    let sumDc = 0;
    let sumTri = 0;
    const start = this._head - this._count;
    for (let i = start; i < this._head; i++) {
      const ri = i % RING_CAPACITY;
      sumFt += this._deltas[ri];
      sumDc += this._drawCalls[ri];
      sumTri += this._triangles[ri];
    }
    this.frameTimeMs = sumFt / this._count;
    this.fps = this.frameTimeMs > 0 ? 1000 / this.frameTimeMs : 0;
    this.drawCalls = sumDc / this._count;
    this.triangles = sumTri / this._count;
    this.textures = info.memory.textures;
    this.geometries = info.memory.geometries;

    // Reset renderer info so next frame gets fresh counts
    info.reset();

    // ── Read performance measures for this frame ────────────────────────────
    let jsTotal = 0;
    for (const section of PERF_SECTIONS) {
      const entries = performance.getEntriesByName(`perf:${section}`, 'measure');
      let duration = 0;
      if (entries.length > 0) {
        duration = entries[entries.length - 1].duration;
      }
      const buf = this._sectionBuffers.get(section)!;
      const head = this._sectionHeads.get(section)!;
      buf[head % RING_CAPACITY] = duration;
      this._sectionHeads.set(section, head + 1);
      jsTotal += duration;
    }

    // jsTotal and gpuInferred
    const jsBuf = this._sectionBuffers.get('jsTotal')!;
    const jsHead = this._sectionHeads.get('jsTotal')!;
    jsBuf[jsHead % RING_CAPACITY] = jsTotal;
    this._sectionHeads.set('jsTotal', jsHead + 1);

    const gpuInferred = Math.max(0, ft - jsTotal);
    const gpuBuf = this._sectionBuffers.get('gpuInferred')!;
    const gpuHead = this._sectionHeads.get('gpuInferred')!;
    gpuBuf[gpuHead % RING_CAPACITY] = gpuInferred;
    this._sectionHeads.set('gpuInferred', gpuHead + 1);

    // Clear only perf-monitor marks/measures to avoid clobbering other tools
    for (const section of PERF_SECTIONS) {
      performance.clearMarks(`perf:${section}:start`);
      performance.clearMarks(`perf:${section}:end`);
      performance.clearMeasures(`perf:${section}`);
    }

    // ── Sampling accumulation ──────────────────────────────────────────────
    if (this._sampling) {
      this._sampleFrames++;
      if (currentFps < this._sampleFpsMin) this._sampleFpsMin = currentFps;
      if (currentFps > this._sampleFpsMax) this._sampleFpsMax = currentFps;
      this._sampleFpsSum += currentFps;

      if (ft < this._sampleFtMin) this._sampleFtMin = ft;
      if (ft > this._sampleFtMax) this._sampleFtMax = ft;
      this._sampleFtSum += ft;

      if (dc < this._sampleDcMin) this._sampleDcMin = dc;
      if (dc > this._sampleDcMax) this._sampleDcMax = dc;
      this._sampleDcSum += dc;

      this._sampleFtValues.push(ft);
      this._sampleFpsValues.push(currentFps);
      for (const key of ALL_TIMING_KEYS) {
        const entries = this._sampleSectionValues.get(key)!;
        const buf = this._sectionBuffers.get(key)!;
        const head = this._sectionHeads.get(key)!;
        entries.push(buf[(head - 1 + RING_CAPACITY) % RING_CAPACITY]);
      }

      const elapsed = performance.now() - this._sampleStart;
      if (elapsed >= this._sampleDuration) {
        this._sampling = false;
        const n = this._sampleFrames;

        const fpsSorted = [...this._sampleFpsValues].sort((a, b) => a - b);
        const ftSorted = [...this._sampleFtValues].sort((a, b) => a - b);

        const timingEntries: Record<string, PerfTimingEntry> = {};
        for (const key of ALL_TIMING_KEYS) {
          const vals = this._sampleSectionValues.get(key)!;
          const sorted = [...vals].sort((a, b) => a - b);
          timingEntries[key] = {
            avg: round(vals.reduce((s, v) => s + v, 0) / vals.length, 2),
            p95: round(percentile(sorted, 95), 2),
          };
        }

        const snapshot: PerfSnapshot = {
          timestamp: new Date().toISOString(),
          durationMs: this._sampleDuration,
          frames: n,
          conditions: {
            runners: this._sampleRunners,
            camera: this._sampleCamera,
            source: this._sampleSource,
          },
          fps: {
            min: round(this._sampleFpsMin, 1),
            avg: round(this._sampleFpsSum / n, 1),
            max: round(this._sampleFpsMax, 1),
            p50: round(percentile(fpsSorted, 50), 1),
            p95: round(percentile(fpsSorted, 95), 1),
            p99: round(percentile(fpsSorted, 99), 1),
          },
          frameTimeMs: {
            min: round(this._sampleFtMin, 1),
            avg: round(this._sampleFtSum / n, 1),
            max: round(this._sampleFtMax, 1),
            p50: round(percentile(ftSorted, 50), 1),
            p95: round(percentile(ftSorted, 95), 1),
            p99: round(percentile(ftSorted, 99), 1),
          },
          drawCalls: {
            min: round(this._sampleDcMin, 0),
            avg: round(this._sampleDcSum / n, 0),
            max: round(this._sampleDcMax, 0),
          },
          triangles: Math.round(this.triangles),
          textures: this.textures,
          geometries: this.geometries,
          timing: timingEntries as PerfSnapshot['timing'],
          label: this._sampleLabel,
        };
        console.log(JSON.stringify(snapshot, null, 2));
        this._sampleOnComplete?.(snapshot);
      }
    }
  }

  /**
   * Begin a timed sampling capture.
   *
   * @param durationMs How long to sample (e.g. 5000 for 5 seconds).
   * @param label A tag for the snapshot (e.g. "baseline").
   * @param runners Current runner count at the time of capture.
   * @param camera Camera mode during capture.
   * @param source Data source during capture.
   * @param onComplete Optional callback fired when the capture finishes.
   */
  startSample(
    durationMs: number,
    label: string,
    runners: number,
    camera: 'static' | 'follow-leader' = 'static',
    source: 'debug-race' | 'backend' = 'debug-race',
    onComplete?: (snapshot: PerfSnapshot) => void,
  ): void {
    this._sampling = true;
    this._sampleStart = performance.now();
    this._sampleDuration = durationMs;
    this._sampleLabel = label;
    this._sampleRunners = runners;
    this._sampleCamera = camera;
    this._sampleSource = source;
    this._sampleOnComplete = onComplete;

    this._sampleFrames = 0;
    this._sampleFpsMin = Infinity;
    this._sampleFpsMax = -Infinity;
    this._sampleFpsSum = 0;
    this._sampleFtMin = Infinity;
    this._sampleFtMax = -Infinity;
    this._sampleFtSum = 0;
    this._sampleDcMin = Infinity;
    this._sampleDcMax = -Infinity;
    this._sampleDcSum = 0;

    this._sampleFtValues = [];
    this._sampleFpsValues = [];
    this._sampleSectionValues.clear();
    for (const key of ALL_TIMING_KEYS) {
      this._sampleSectionValues.set(key, []);
    }
  }
}

function round(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}
