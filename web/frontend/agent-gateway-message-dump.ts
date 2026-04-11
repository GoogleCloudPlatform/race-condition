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
 * NDJSON capture of every inbound WebSocket message handled by AgentGateway (always on).
 *
 * Each line stores decoded gateway fields: `wrapperType`, `event`, parsed JSON `data`, and optional
 * wall-clock `timestamp` (from the gateway wrapper) for replay pacing. Optional `t` is legacy
 * `performance.now()` capture. No `MessageEvent` metadata unless you add it yourself.
 * Legacy dumps with `rawBase64` per line still replay as raw wire frames; thin dumps use
 * {@link AgentGatewayInboundRecord} plus {@link ReplayAgentGatewayMsgOptions.encodeSemanticLine}.
 *
 * Manual download: `window.__csAgentGatewayMsgDebugDownload()` — buffer fills as messages arrive and
 * is cleared after a successful download.
 *
 * Download filename: agent-gateway-msg-{activeDemo}-{YYYY-MM-DD}.ndjson
 * Active demo comes from window.__csActiveDemoKey (set by DemoService).
 *
 * Replay (dev): `replayAgentGatewayMsgNdjsonText(handleMessage, text, { encodeSemanticLine })`
 * for thin dumps (pass `encodeSemanticLine` from the gateway singleton’s `encodeInboundRecordForReplay`).
 * Legacy: `parseAgentGatewayMsgNdjsonToArrayBuffers` + `replayAgentGatewayMessages` when lines include `rawBase64`.
 *
 * For **semantic** NDJSON (no `rawBase64`), chronological replay uses wall `timestamp` deltas (see
 * {@link parseAgentGatewayMsgNdjsonInterFrameReplayMeta}). Long sim–sim gaps **inside** the marathon
 * window (first `fire_start_gun` through `check_race_complete` with `race_complete`) are collapsed to
 * {@link HARDCODED_SIM_TICK_INTERVAL_SEC} so wall time matches live `advance_tick` (~120s over 12 ticks at 1×).
 * Outside that window, recorded spacing is preserved. Optional {@link ReplayAgentGatewayMsgOptions.tickAlignedSimulation}
 * still reorders by tick bucket for manual callers only. Binary `rawBase64` dumps apply `timingScale` to every gap
 * (tool names are not decoded).
 */

import { HARDCODED_SIM_TICK_INTERVAL_SEC } from './src/app/runner-sim-constants';

/** Dispatched on `window` when the in-memory dump buffer length changes ({@link agentGatewayMsgDumpLineCount}). */
export const AGENT_GATEWAY_MSG_DUMP_CHANGED = 'cs:agent-gateway-msg-dump-changed';

let lines: string[] = [];

function notifyAgentGatewayMsgDumpChanged(): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(
      new CustomEvent(AGENT_GATEWAY_MSG_DUMP_CHANGED, { detail: { count: lines.length } }),
    );
  } catch {
    /* ignore */
  }
}

function safeStringify(obj: unknown): string {
  try {
    return JSON.stringify(obj, (_k, v) => (typeof v === 'bigint' ? v.toString() : v));
  } catch (e) {
    return JSON.stringify({
      _error: 'stringify_failed',
      message: String(e),
    });
  }
}

function getDemoKeyForFilename(): string {
  try {
    if (typeof window !== 'undefined') {
      const w = window as Window & { __csActiveDemoKey?: string };
      if (w.__csActiveDemoKey) return String(w.__csActiveDemoKey);
    }
  } catch {
    /* ignore */
  }
  return 'unknown';
}

function localDateYmd(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function sanitizeFilenameSegment(s: string): string {
  const t = s.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/_+/g, '_');
  return (t.slice(0, 80) || 'unknown').replace(/^_|_$/g, '') || 'unknown';
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

/**
 * One line from an agent-gateway NDJSON dump.
 * Legacy lines include `rawBase64` (WebSocket frame body) for binary replay.
 */
export interface AgentGatewayMsgDumpLine {
  ts?: string;
  /** Wall-clock time (e.g. ISO 8601) for inter-frame delay replay when both lines have a parseable value. */
  timestamp?: string;
  t?: number;
  kind?: string;
  messageEventType?: string;
  dataKind?: string;
  byteLength?: number;
  rawBase64?: string | null;
  /** Present when `target` is a WebSocket (same connection URL you see on the event in DevTools). */
  wsUrl?: string;
  wrapperType?: string;
  event?: string;
  /** Parsed JSON payload from the gateway wrapper (semantic capture). */
  data?: Record<string, unknown>;
}

/** Snapshot of protobuf `Origin` for thin NDJSON capture / replay (protobufjs camelCase). */
export interface AgentGatewayOriginCapture {
  type?: string;
  id?: string;
  sessionId?: string;
  displayName?: string;
}

export interface AgentGatewayInboundRecord {
  wrapperType: string;
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
  /** Present when recorded live; restores speaker labels during thin replay. */
  origin?: AgentGatewayOriginCapture;
  /** Exact chat speaker string from live handling; preferred on replay (via wrapper metadata). */
  speaker?: string;
}

function parseInboundRecordOrigin(raw: unknown): AgentGatewayOriginCapture | undefined {
  if (raw === undefined || raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return undefined;
  }
  const r = raw as Record<string, unknown>;
  const str = (k: string): string | undefined => {
    const v = r[k];
    return typeof v === 'string' && v.length > 0 ? v : undefined;
  };
  const type = str('type');
  const id = str('id');
  const sessionId = str('sessionId');
  const displayName = str('displayName');
  if (!type && !id && !sessionId && !displayName) return undefined;
  const out: AgentGatewayOriginCapture = {};
  if (type) out.type = type;
  if (id) out.id = id;
  if (sessionId) out.sessionId = sessionId;
  if (displayName) out.displayName = displayName;
  return out;
}

/**
 * Parses NDJSON where each line is `{ wrapperType, event, data }` (optional `origin`, `timestamp`).
 */
export function parseAgentGatewayMsgNdjsonToInboundRecords(
  ndjsonText: string,
): AgentGatewayInboundRecord[] {
  const out: AgentGatewayInboundRecord[] = [];
  for (const rawLine of ndjsonText.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      const row = JSON.parse(line) as Record<string, unknown>;
      const wrapperType = row['wrapperType'];
      const event = row['event'];
      const data = row['data'];
      const rawTimestamp = row['timestamp'];
      const timestamp = typeof rawTimestamp === 'string' ? rawTimestamp : '';
      if (typeof wrapperType !== 'string' || typeof event !== 'string') continue;
      const dataObj =
        data !== undefined && typeof data === 'object' && data !== null && !Array.isArray(data)
          ? (data as Record<string, unknown>)
          : {};
      const origin = parseInboundRecordOrigin(row['origin']);
      const rawSpeaker = row['speaker'];
      const speaker =
        typeof rawSpeaker === 'string' && rawSpeaker.length > 0 ? rawSpeaker : undefined;
      const rec: AgentGatewayInboundRecord = { wrapperType, event, data: dataObj, timestamp };
      if (origin) rec.origin = origin;
      if (speaker) rec.speaker = speaker;
      out.push(rec);
    } catch {
      /* skip bad line */
    }
  }
  return out;
}

/**
 * Decodes every line that has `rawBase64` (arraybuffer/string captures; blob-only lines are skipped).
 */
export function parseAgentGatewayMsgNdjsonToArrayBuffers(ndjsonText: string): ArrayBuffer[] {
  const out: ArrayBuffer[] = [];
  for (const rawLine of ndjsonText.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      const row = JSON.parse(line) as AgentGatewayMsgDumpLine;
      if (!row.rawBase64) continue;
      out.push(base64ToArrayBuffer(row.rawBase64));
    } catch {
      /* skip bad line */
    }
  }
  return out;
}

function parseDumpLineWallClockMs(row: Record<string, unknown>): number | undefined {
  const ts = row['timestamp'];
  if (typeof ts !== 'string' || !ts.trim()) return undefined;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? undefined : ms;
}

function parseDumpLinePerformanceMs(row: Record<string, unknown>): number | undefined {
  const t = row['t'];
  return typeof t === 'number' && !Number.isNaN(t) ? t : undefined;
}

/**
 * Marathon simulation tool names as sent on `tool_start` (`data.tool`) / `tool_end` (`data.tool_name`).
 * Kept in sync with `TOOLS` in `agent-gateway-updates.ts`.
 */
export const SIMULATION_GATEWAY_TOOL_NAMES = new Set<string>([
  'start_simulation',
  'prepare_simulation',
  'spawn_runners',
  'fire_start_gun',
  'advance_tick',
  'process_tick',
  'check_race_complete',
  'compile_results',
]);

/**
 * Whether a single NDJSON object line is a simulation-timed gateway event (ticks, runners, race pipeline).
 */
export function isSimulationTimedGatewayDumpRow(row: Record<string, unknown>): boolean {
  const event = row['event'];
  if (event !== 'tool_start' && event !== 'tool_end') return false;
  const data = row['data'];
  if (data === undefined || typeof data !== 'object' || data === null || Array.isArray(data)) {
    return false;
  }
  const d = data as Record<string, unknown>;
  if (event === 'tool_start') {
    const tool = d['tool'];
    return typeof tool === 'string' && SIMULATION_GATEWAY_TOOL_NAMES.has(tool);
  }
  const toolName = d['tool_name'];
  return typeof toolName === 'string' && SIMULATION_GATEWAY_TOOL_NAMES.has(toolName);
}

/** `data.result.tick` from a `tool_end` line when present. */
export function toolEndResultTick(data: Record<string, unknown>): number | undefined {
  const result = data['result'];
  if (
    result === undefined ||
    typeof result !== 'object' ||
    result === null ||
    Array.isArray(result)
  ) {
    return undefined;
  }
  const t = (result as Record<string, unknown>)['tick'];
  return typeof t === 'number' && !Number.isNaN(t) ? t : undefined;
}

/**
 * True for thin NDJSON rows that are a runner `process_tick` tool completion.
 * Used to collapse inter-frame delays inside a tick burst (timestamps are often out of order).
 */
export function isRunnerProcessTickToolEndRow(row: Record<string, unknown>): boolean {
  if (row['event'] !== 'tool_end') return false;
  const data = row['data'];
  if (data === undefined || typeof data !== 'object' || data === null || Array.isArray(data)) {
    return false;
  }
  const d = data as Record<string, unknown>;
  return d['tool_name'] === 'process_tick';
}

/**
 * Whether replay should use 0 ms between two consecutive thin rows (same tick burst).
 * Collapses when both are `process_tick` ends and `result.tick` matches if both present;
 * if either tick is missing, still collapse (parallel runners usually share tick).
 */
export function shouldCollapseRunnerProcessTickReplayGap(
  prevRow: Record<string, unknown>,
  nextRow: Record<string, unknown>,
): boolean {
  if (!isRunnerProcessTickToolEndRow(prevRow) || !isRunnerProcessTickToolEndRow(nextRow)) {
    return false;
  }
  const prevData = prevRow['data'] as Record<string, unknown>;
  const nextData = nextRow['data'] as Record<string, unknown>;
  const a = toolEndResultTick(prevData);
  const b = toolEndResultTick(nextData);
  if (a !== undefined && b !== undefined && a !== b) return false;
  return true;
}

function isFireStartGunDumpRow(row: Record<string, unknown>): boolean {
  const ev = row['event'];
  const data = row['data'];
  if (data === undefined || typeof data !== 'object' || data === null || Array.isArray(data)) {
    return false;
  }
  const d = data as Record<string, unknown>;
  if (ev === 'tool_start') {
    return d['tool'] === 'fire_start_gun';
  }
  if (ev === 'tool_end') {
    return d['tool_name'] === 'fire_start_gun';
  }
  return false;
}

function isCheckRaceCompleteRaceDoneDumpRow(row: Record<string, unknown>): boolean {
  if (row['event'] !== 'tool_end') return false;
  const data = row['data'];
  if (data === undefined || typeof data !== 'object' || data === null || Array.isArray(data)) {
    return false;
  }
  const d = data as Record<string, unknown>;
  if (d['tool_name'] !== 'check_race_complete') return false;
  const result = d['result'];
  if (
    result === undefined ||
    typeof result !== 'object' ||
    result === null ||
    Array.isArray(result)
  ) {
    return false;
  }
  return (result as Record<string, unknown>)['status'] === 'race_complete';
}

/**
 * First/last stamp indices for marathon wall pacing: `fire_start_gun` … `check_race_complete` (`race_complete`).
 * Thin rows only; returns null if anchors are missing or out of order.
 */
function findMarathonWallClockPacingIndices(
  stamps: ReadonlyArray<{ thinRow?: Record<string, unknown> }>,
): { start: number; end: number } | null {
  let start = -1;
  let end = -1;
  for (let i = 0; i < stamps.length; i++) {
    const row = stamps[i].thinRow;
    if (!row) continue;
    if (start < 0 && isFireStartGunDumpRow(row)) {
      start = i;
    }
    if (isCheckRaceCompleteRaceDoneDumpRow(row)) {
      end = i;
    }
  }
  if (start < 0 || end < 0 || end < start) return null;
  return { start, end };
}

/**
 * For each consecutive pair of replayed dump lines (same inclusion rules as frame extraction:
 * lines with `rawBase64`, or thin `{ wrapperType, event, data }` lines), computes the wait before
 * the next frame:
 *
 * 1. If **both** lines have a parseable {@link AgentGatewayInboundRecord.timestamp} string →
 *    `max(0, nextWallMs - prevWallMs)`.
 * 2. Else if **both** have numeric {@link AgentGatewayMsgDumpLine.t} → `max(0, nextT - prevT)` (legacy).
 * 3. Else → `fallbackMs` (typically {@link ReplayAgentGatewayMsgOptions.intervalMs}).
 *
 * Wall-clock and `t` are never mixed for one gap.
 *
 * {@link interFrameApplyTimingScale}: per gap, `true` means apply global {@link ReplayAgentGatewayMsgOptions.timingScale}
 * to that wait; `false` means use scale `1` (full recorded delay). `true` when **both** lines are non-simulation,
 * or when both are simulation-timed and the delay was **replaced** with one tick interval (see below). For `rawBase64`
 * lines, endpoints are treated as non-simulation (unknown), so those gaps still use `timingScale` when paired with
 * another non-sim line.
 *
 * Gaps between consecutive runner `process_tick` `tool_end` rows (see
 * {@link shouldCollapseRunnerProcessTickReplayGap}) use **0 ms** so out-of-order capture timestamps do not inflate
 * wall-clock replay between `advance_tick` boundaries.
 *
 * When **both** endpoints are simulation-timed, the recorded delay is **greater** than one marathon tick wall
 * interval ({@link HARDCODED_SIM_TICK_INTERVAL_SEC}), **and** both lines fall between the first `fire_start_gun`
 * and `check_race_complete` (`race_complete`) inclusive, the delay is replaced with that interval so cached
 * replay matches a non-recorded run; `timingScale` then applies to that synthetic gap. Outside that window,
 * long sim–sim gaps keep recorded timing.
 */
export function parseAgentGatewayMsgNdjsonInterFrameReplayMeta(
  ndjsonText: string,
  fallbackMs: number,
): { delays: number[]; interFrameApplyTimingScale: boolean[] } {
  type Stamp = {
    wallMs?: number;
    perfMs?: number;
    isSimTimed: boolean;
    /** Original thin NDJSON object; omitted for `rawBase64` lines. */
    thinRow?: Record<string, unknown>;
  };
  const stamps: Stamp[] = [];
  for (const rawLine of ndjsonText.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      const row = JSON.parse(line) as Record<string, unknown>;
      if (typeof row['rawBase64'] === 'string' && row['rawBase64']) {
        stamps.push({
          wallMs: parseDumpLineWallClockMs(row),
          perfMs: parseDumpLinePerformanceMs(row),
          isSimTimed: false,
        });
        continue;
      }
      if (
        typeof row['wrapperType'] === 'string' &&
        typeof row['event'] === 'string' &&
        row['data'] !== undefined &&
        typeof row['data'] === 'object' &&
        row['data'] !== null &&
        !Array.isArray(row['data'])
      ) {
        stamps.push({
          wallMs: parseDumpLineWallClockMs(row),
          perfMs: parseDumpLinePerformanceMs(row),
          isSimTimed: isSimulationTimedGatewayDumpRow(row),
          thinRow: row,
        });
      }
    } catch {
      /* skip bad line */
    }
  }
  const marathonWindow = findMarathonWallClockPacingIndices(stamps);
  const delays: number[] = [];
  const interFrameApplyTimingScale: boolean[] = [];
  const tickIntervalMs = HARDCODED_SIM_TICK_INTERVAL_SEC * 1000;
  for (let i = 0; i < stamps.length - 1; i++) {
    const a = stamps[i];
    const b = stamps[i + 1];
    const aw = a.wallMs;
    const bw = b.wallMs;
    let delay: number;
    if (aw !== undefined && bw !== undefined) {
      delay = Math.max(0, bw - aw);
    } else {
      const ap = a.perfMs;
      const bp = b.perfMs;
      if (ap !== undefined && bp !== undefined) {
        delay = Math.max(0, bp - ap);
      } else {
        delay = fallbackMs;
      }
    }
    if (
      a.thinRow !== undefined &&
      b.thinRow !== undefined &&
      shouldCollapseRunnerProcessTickReplayGap(a.thinRow, b.thinRow)
    ) {
      delay = 0;
    }

    let replacedSimTickCadence = false;
    const gapInsideMarathonWindow =
      marathonWindow !== null && i >= marathonWindow.start && i + 1 <= marathonWindow.end;
    if (a.isSimTimed && b.isSimTimed && delay > tickIntervalMs && gapInsideMarathonWindow) {
      delay = tickIntervalMs;
      replacedSimTickCadence = true;
    }

    let applyScale: boolean;
    if (replacedSimTickCadence) {
      applyScale = true;
    } else {
      applyScale = !a.isSimTimed && !b.isSimTimed;
    }
    delays.push(delay);
    interFrameApplyTimingScale.push(applyScale);
  }
  return { delays, interFrameApplyTimingScale };
}

export function parseAgentGatewayMsgNdjsonInterFrameDelays(
  ndjsonText: string,
  fallbackMs: number,
): number[] {
  return parseAgentGatewayMsgNdjsonInterFrameReplayMeta(ndjsonText, fallbackMs).delays;
}

function isCompileResultsGatewayLine(rec: AgentGatewayInboundRecord): boolean {
  if (rec.event === 'tool_end' && rec.data['tool_name'] === 'compile_results') return true;
  if (rec.event === 'tool_start' && rec.data['tool'] === 'compile_results') return true;
  return false;
}

/**
 * Assigns each inbound record to a marathon tick bucket for {@link buildTickAlignedReplaySchedule}.
 * `pre` is before the first `advance_tick` / `process_tick` tick anchor; race ticks are `0 … max_ticks-1`;
 * `post` starts at `compile_results`.
 */
export function assignTickAlignedBuckets(
  records: AgentGatewayInboundRecord[],
): ('pre' | number | 'post')[] {
  const out: ('pre' | number | 'post')[] = [];
  let currentTick: number | null = null;
  let postMode = false;
  for (let i = 0; i < records.length; i++) {
    const rec = records[i];
    if (postMode) {
      out.push('post');
      continue;
    }
    if (isCompileResultsGatewayLine(rec)) {
      postMode = true;
      out.push('post');
      continue;
    }
    if (rec.event === 'tool_end') {
      const tn = rec.data['tool_name'];
      if (tn === 'advance_tick') {
        const t = toolEndResultTick(rec.data);
        if (t !== undefined) currentTick = t;
        out.push(currentTick !== null ? currentTick : 'pre');
        continue;
      }
      if (tn === 'process_tick') {
        const t = toolEndResultTick(rec.data);
        if (t !== undefined) currentTick = t;
        out.push(currentTick !== null ? currentTick : 'pre');
        continue;
      }
    }
    if (currentTick === null) out.push('pre');
    else out.push(currentTick);
  }
  return out;
}

/**
 * Segment id for ordering: `pre` alone (0), tick 0 (1), ticks 1…11 (2…12), `post` (13).
 * Pre-race is split from tick 0 so replay can yield to the browser before the race-engine burst.
 */
export function segmentIdFromTickBucket(b: 'pre' | number | 'post'): number {
  if (b === 'pre') return 0;
  if (b === 0) return 1;
  if (b === 'post') return 13;
  return (b as number) + 1;
}

function delayMsBetweenTickSegments(si: number, sj: number, tickIntervalMs: number): number {
  if (si === sj) return 0;
  if (si === 0 && sj === 1) return 0;
  if (sj === 13 && si === 12) return 0;
  if (sj > si) return (sj - si) * tickIntervalMs;
  return 0;
}

/**
 * Reorders frames into tick-aligned segments (pre-race, then tick 0 … tick 11, then post) and
 * yields inter-frame delays: 0 within a segment; between segments uses
 * `(seg_j - seg_i) * tickInterval` except pre→tick0 and tick11→post (0 ms wall).
 *
 * Simulated race time advances **30 minutes per tick** (6h over 12 ticks); wall spacing between
 * tick bursts is {@link HARDCODED_SIM_TICK_INTERVAL_SEC}s (12× → 120s at 1×), matching live `advance_tick`.
 */
export function buildTickAlignedReplaySchedule(
  records: AgentGatewayInboundRecord[],
  frames: ArrayBuffer[],
): {
  frames: ArrayBuffer[];
  interFrameDelaysMs: number[];
  interFrameApplyTimingScale: boolean[];
  /** Last index in reordered `frames` whose bucket is `pre`; -1 if none. */
  lastPreReorderIndex: number;
} | null {
  if (records.length !== frames.length || records.length < 2) return null;
  const buckets = assignTickAlignedBuckets(records);
  const n = records.length;
  const order = Array.from({ length: n }, (_, i) => i);
  order.sort((a, b) => {
    const sa = segmentIdFromTickBucket(buckets[a]);
    const sb = segmentIdFromTickBucket(buckets[b]);
    if (sa !== sb) return sa - sb;
    return a - b;
  });
  let lastPreReorderIndex = -1;
  for (let k = 0; k < n; k++) {
    if (buckets[order[k]] === 'pre') lastPreReorderIndex = k;
  }
  const tickIntervalMs = HARDCODED_SIM_TICK_INTERVAL_SEC * 1000;
  const interFrameDelaysMs: number[] = [];
  const interFrameApplyTimingScale: boolean[] = [];
  for (let k = 0; k < n - 1; k++) {
    const i = order[k];
    const j = order[k + 1];
    const si = segmentIdFromTickBucket(buckets[i]);
    const sj = segmentIdFromTickBucket(buckets[j]);
    const ms = delayMsBetweenTickSegments(si, sj, tickIntervalMs);
    interFrameDelaysMs.push(ms);
    interFrameApplyTimingScale.push(ms > 0);
  }
  const reordered = order.map((idx) => frames[idx]);
  return {
    frames: reordered,
    interFrameDelaysMs,
    interFrameApplyTimingScale,
    lastPreReorderIndex,
  };
}

/**
 * Plays tick-aligned frames in two phases so pre-race lines can paint before the tick-0 burst:
 * after the last `pre` frame, waits `gapAfterPreMs` (0 → `setTimeout(0)`), then plays the rest.
 */
function replayTickAlignedAfterPreRace(
  handleMessage: (messageEvent: MessageEvent) => void,
  frames: ArrayBuffer[],
  interFrameDelaysMs: number[],
  interFrameApplyTimingScale: boolean[] | undefined,
  lastPreReorderIndex: number,
  opts: ReplayAgentGatewayMsgOptions,
): () => void {
  const n = frames.length;
  if (lastPreReorderIndex < 0 || lastPreReorderIndex >= n - 1) {
    return replayAgentGatewayMessages(handleMessage, frames, {
      ...opts,
      interFrameDelaysMs,
      interFrameApplyTimingScale,
    });
  }

  const partA = frames.slice(0, lastPreReorderIndex + 1);
  const delaysA =
    lastPreReorderIndex > 0 ? interFrameDelaysMs.slice(0, lastPreReorderIndex) : undefined;
  const applyA =
    interFrameApplyTimingScale && lastPreReorderIndex > 0
      ? interFrameApplyTimingScale.slice(0, lastPreReorderIndex)
      : undefined;
  const gapAfterPreMs = interFrameDelaysMs[lastPreReorderIndex];

  const partB = frames.slice(lastPreReorderIndex + 1);
  const delaysB = partB.length > 1 ? interFrameDelaysMs.slice(lastPreReorderIndex + 1) : undefined;
  const applyB =
    interFrameApplyTimingScale && partB.length > 1
      ? interFrameApplyTimingScale.slice(lastPreReorderIndex + 1)
      : undefined;

  let timerBetween: ReturnType<typeof setTimeout> | undefined;
  let cancelB: () => void = () => {};

  const cancelA = replayAgentGatewayMessages(handleMessage, partA, {
    ...opts,
    interFrameDelaysMs: delaysA,
    interFrameApplyTimingScale: applyA,
    onComplete: () => {
      const timingScale = resolveTimingScale(opts);
      const scalePreGap =
        interFrameApplyTimingScale &&
        lastPreReorderIndex < interFrameApplyTimingScale.length &&
        interFrameApplyTimingScale[lastPreReorderIndex] === false
          ? 1
          : timingScale;
      const scaledGapAfterPre = Math.max(0, gapAfterPreMs / scalePreGap);
      const wait = gapAfterPreMs > 0 ? scaledGapAfterPre : 0;
      timerBetween = setTimeout(() => {
        timerBetween = undefined;
        cancelB = replayAgentGatewayMessages(handleMessage, partB, {
          ...opts,
          interFrameDelaysMs: delaysB,
          interFrameApplyTimingScale: applyB,
        });
      }, wait);
    },
  });

  return () => {
    cancelA();
    if (timerBetween !== undefined) {
      clearTimeout(timerBetween);
      timerBetween = undefined;
    }
    cancelB();
  };
}

/**
 * Reads a file as NDJSON and returns only `rawBase64` frames. Replay pacing uses wall-clock
 * deltas or `t` via {@link replayAgentGatewayMsgNdjsonText} with `useRecordedPerformanceTimestamps`.
 */
export async function parseAgentGatewayMsgNdjsonFile(file: File): Promise<ArrayBuffer[]> {
  const text = await file.text();
  return parseAgentGatewayMsgNdjsonToArrayBuffers(text);
}

export interface ReplayAgentGatewayMsgOptions {
  /**
   * When NDJSON lines have no `rawBase64`, each line is treated as {@link AgentGatewayInboundRecord}
   * and this encodes wire bytes for `handleMessage` (e.g. `agentGateway.encodeInboundRecordForReplay`).
   */
  encodeSemanticLine?: (rec: AgentGatewayInboundRecord) => ArrayBuffer | null;
  /** Milliseconds between frames when not using per-gap delays; default 2000. Fallback when a gap cannot be derived from recorded `timestamp` or `t` (see {@link parseAgentGatewayMsgNdjsonInterFrameDelays}). */
  intervalMs?: number;
  /**
   * If true (default), the first frame is delivered immediately; later frames wait `intervalMs`.
   * If false, wait `intervalMs` before the first frame.
   */
  immediateFirst?: boolean;
  /** Called once after the last frame is delivered (not called when {@link replayAgentGatewayMessages}’s cancel runs). */
  onComplete?: () => void;
  /**
   * Milliseconds to wait after frame `i` before delivering frame `i + 1`. Length must be
   * `frames.length - 1`. When omitted, every gap uses {@link intervalMs}.
   */
  interFrameDelaysMs?: number[];
  /**
   * Per gap after frame `i`: if `true`, scale the wait by {@link timingScale}; if `false`, use scale `1`.
   * Length must be `frames.length - 1` when set. Omitted means every gap uses `timingScale`.
   * Semantic NDJSON replay sets this from {@link parseAgentGatewayMsgNdjsonInterFrameReplayMeta} (non-sim gaps and
   * replaced long sim–sim tick-interval gaps may use `timingScale`; other sim–sim gaps use full recorded delay).
   */
  interFrameApplyTimingScale?: boolean[];
  /**
   * Only for {@link replayAgentGatewayMsgNdjsonText}: set gaps from each line’s wall-clock `timestamp`
   * when both sides parse, else from legacy `t` when both present (see {@link parseAgentGatewayMsgNdjsonInterFrameDelays}).
   * Ignored if {@link interFrameDelaysMs} is set. {@link timingScale} applies per {@link interFrameApplyTimingScale}.
   */
  useRecordedPerformanceTimestamps?: boolean;
  /**
   * When true (thin NDJSON only), ignore recorded wall-clock gaps and instead bucket by marathon tick
   * ({@link assignTickAlignedBuckets}) so pre ∪ tick 0 play at t=0, then tick 1…`max_ticks-1` each
   * after {@link HARDCODED_SIM_TICK_INTERVAL_SEC}, then post. Requires one encoded frame per parsed record.
   * Ignored if {@link interFrameDelaysMs} is set or raw `rawBase64` frames are used.
   */
  tickAlignedSimulation?: boolean;
  /**
   * Speed multiplier for waits where {@link interFrameApplyTimingScale} is absent or `true` for that gap:
   * `baseMs / timingScale` (default `1`). E.g. `2` replays twice as fast; `0.5` half speed.
   * Non-positive or non-finite values are treated as `1`. For semantic NDJSON, long sim–sim gaps replaced with one
   * tick interval use `timingScale`; purely non-sim gaps use it when both endpoints are non-simulation.
   */
  timingScale?: number;
  /**
   * If set, called whenever a gap’s scale is needed; return value overrides {@link timingScale} for that read.
   * Use for UI-driven speed that may change while replay is in progress (subsequent gaps pick up the new value).
   */
  getTimingScale?: () => number;
}

function resolveTimingScale(opts?: ReplayAgentGatewayMsgOptions): number {
  const raw = opts?.getTimingScale ? opts.getTimingScale() : opts?.timingScale;
  return typeof raw === 'number' && raw > 0 && Number.isFinite(raw) ? raw : 1;
}

/**
 * Invokes `handleMessage` with synthetic `MessageEvent`s whose `data` is each frame’s `ArrayBuffer`,
 * matching the monitor WebSocket (`binaryType = "arraybuffer"`).
 *
 * @returns `stop` — call to cancel pending deliveries.
 */
export function replayAgentGatewayMessages(
  handleMessage: (messageEvent: MessageEvent) => void,
  frames: ArrayBuffer[],
  opts?: ReplayAgentGatewayMsgOptions,
): () => void {
  const intervalMs = opts?.intervalMs ?? 2000;
  const immediateFirst = opts?.immediateFirst !== false;
  const onComplete = opts?.onComplete;
  const explicitDelays = opts?.interFrameDelaysMs;
  const useVariableDelays =
    explicitDelays !== undefined &&
    frames.length > 1 &&
    explicitDelays.length === frames.length - 1;
  const gapScaleFlags = opts?.interFrameApplyTimingScale;
  const effectiveScaleForGap = (gapIndex: number): number => {
    if (
      gapScaleFlags !== undefined &&
      gapIndex < gapScaleFlags.length &&
      gapScaleFlags[gapIndex] === false
    ) {
      return 1;
    }
    return resolveTimingScale(opts);
  };
  const scaleMsForGap = (ms: number, gapIndex: number) =>
    Math.max(0, ms / effectiveScaleForGap(gapIndex));

  let timer: ReturnType<typeof setTimeout> | undefined;
  let finished = false;

  const cancel = () => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  const notifyComplete = () => {
    if (finished) return;
    finished = true;
    onComplete?.();
  };

  const gapAfterFrame = (deliveredIndex: number): number => {
    if (useVariableDelays) {
      return explicitDelays![deliveredIndex];
    }
    return intervalMs;
  };

  const deliverFrame = (i: number) => {
    handleMessage(new MessageEvent('message', { data: frames[i] }));
  };

  /**
   * After `deliveredIndex`, play forward: **0 ms gaps** run synchronously in one turn (no `setTimeout(0)`
   * per frame — that would smear tick bursts across real seconds). Only strictly positive delays use
   * `setTimeout`, so tick-aligned replay hits ~10s wall between tick segments.
   */
  const scheduleAfterDelivered = (deliveredIndex: number) => {
    let i = deliveredIndex;
    while (i + 1 < frames.length) {
      const delay = scaleMsForGap(gapAfterFrame(i), i);
      if (delay > 0) {
        timer = setTimeout(() => {
          timer = undefined;
          deliverFrame(i + 1);
          scheduleAfterDelivered(i + 1);
        }, delay);
        return;
      }
      i += 1;
      deliverFrame(i);
    }
    notifyComplete();
  };

  if (frames.length === 0) return cancel;

  if (immediateFirst) {
    deliverFrame(0);
    if (frames.length === 1) {
      notifyComplete();
    } else {
      scheduleAfterDelivered(0);
    }
  } else {
    timer = setTimeout(
      () => {
        timer = undefined;
        deliverFrame(0);
        if (frames.length === 1) {
          notifyComplete();
        } else {
          scheduleAfterDelivered(0);
        }
      },
      Math.max(0, intervalMs / resolveTimingScale(opts)),
    );
  }

  return cancel;
}

/**
 * Parses NDJSON text then runs {@link replayAgentGatewayMessages}.
 */
export function replayAgentGatewayMsgNdjsonText(
  handleMessage: (messageEvent: MessageEvent) => void,
  ndjsonText: string,
  opts?: ReplayAgentGatewayMsgOptions,
): () => void {
  let frames = parseAgentGatewayMsgNdjsonToArrayBuffers(ndjsonText);
  let semanticRecords: AgentGatewayInboundRecord[] | undefined;
  if (frames.length === 0) {
    const encode = opts?.encodeSemanticLine;
    if (!encode) {
      console.warn(
        '[agent-gateway replay] NDJSON has no rawBase64 frames. For thin dumps ({ wrapperType, event, data }), pass encodeSemanticLine (e.g. agentGateway.encodeInboundRecordForReplay).',
      );
      return () => {};
    }
    semanticRecords = parseAgentGatewayMsgNdjsonToInboundRecords(ndjsonText);
    const next: ArrayBuffer[] = [];
    for (const rec of semanticRecords) {
      const buf = encode(rec);
      if (buf && buf.byteLength > 0) next.push(buf);
    }
    if (next.length === 0) {
      console.warn(
        '[agent-gateway replay] No frames produced from semantic NDJSON (encode returned empty).',
      );
      return () => {};
    }
    frames = next;
  }
  const intervalMs = opts?.intervalMs ?? 2000;
  let interFrameDelaysMs = opts?.interFrameDelaysMs;
  let interFrameApplyTimingScale = opts?.interFrameApplyTimingScale;
  let tickAlignedPreRaceSplitAt: number | null = null;
  if (
    !interFrameDelaysMs?.length &&
    opts?.tickAlignedSimulation &&
    semanticRecords &&
    frames.length > 1
  ) {
    const sched = buildTickAlignedReplaySchedule(semanticRecords, frames);
    if (sched) {
      frames = sched.frames;
      interFrameDelaysMs = sched.interFrameDelaysMs;
      interFrameApplyTimingScale = sched.interFrameApplyTimingScale;
      const lp = sched.lastPreReorderIndex;
      if (lp >= 0 && lp < frames.length - 1) {
        tickAlignedPreRaceSplitAt = lp;
      }
    } else {
      console.warn(
        'AgentGateway replay: tick-aligned schedule unavailable (encode must produce one frame per NDJSON record); using recorded timestamps or intervalMs',
      );
    }
  }
  if (!interFrameDelaysMs?.length && opts?.useRecordedPerformanceTimestamps && frames.length > 1) {
    const meta = parseAgentGatewayMsgNdjsonInterFrameReplayMeta(ndjsonText, intervalMs);
    interFrameDelaysMs = meta.delays;
    interFrameApplyTimingScale = meta.interFrameApplyTimingScale;
    if (interFrameDelaysMs.length !== frames.length - 1) {
      console.warn(
        'AgentGateway replay: inter-frame delay count mismatch; using fixed intervalMs',
        interFrameDelaysMs.length,
        frames.length,
      );
      interFrameDelaysMs = undefined;
      interFrameApplyTimingScale = undefined;
    }
  }
  if (
    tickAlignedPreRaceSplitAt !== null &&
    interFrameDelaysMs?.length &&
    opts?.tickAlignedSimulation
  ) {
    return replayTickAlignedAfterPreRace(
      handleMessage,
      frames,
      interFrameDelaysMs,
      interFrameApplyTimingScale,
      tickAlignedPreRaceSplitAt,
      { ...opts, intervalMs },
    );
  }
  return replayAgentGatewayMessages(handleMessage, frames, {
    ...opts,
    intervalMs,
    interFrameDelaysMs,
    interFrameApplyTimingScale,
  });
}

/**
 * Records one inbound gateway message. Only {@link AgentGatewayInboundRecord} fields are persisted
 * (no `MessageEvent` fields).
 */
export function recordAgentGatewayInboundMessage(rec: AgentGatewayInboundRecord): void {
  const payload: Record<string, unknown> = {
    wrapperType: rec.wrapperType,
    event: rec.event,
    data: rec.data,
  };
  if (typeof rec.timestamp === 'string' && rec.timestamp.length > 0) {
    payload['timestamp'] = rec.timestamp;
  }
  if (rec.origin && Object.keys(rec.origin).length > 0) {
    payload['origin'] = rec.origin;
  }
  if (typeof rec.speaker === 'string' && rec.speaker.length > 0) {
    payload['speaker'] = rec.speaker;
  }
  const line = safeStringify(payload);
  lines.push(line);
  notifyAgentGatewayMsgDumpChanged();
}

export function agentGatewayMsgDumpLineCount(): number {
  return lines.length;
}

export function clearAgentGatewayMsgDump(): void {
  lines = [];
  notifyAgentGatewayMsgDumpChanged();
}

export function downloadAgentGatewayMessageDump(): void {
  if (!lines.length) {
    console.warn(
      '[agent-gateway msg dump] Nothing to download (0 lines). Inbound gateway messages fill the buffer; ' +
        'receive traffic first, then try again.',
    );
    return;
  }
  const demo = sanitizeFilenameSegment(getDemoKeyForFilename());
  const date = localDateYmd();
  const blob = new Blob([lines.join('\n')], {
    type: 'application/x-ndjson;charset=utf-8',
  });
  const a = document.createElement('a');
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = `agent-gateway-msg-${demo}-${date}.ndjson`;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  lines = [];
  notifyAgentGatewayMsgDumpChanged();
}

declare global {
  interface Window {
    __csAgentGatewayMsgDebugDownload?: () => void;
    /** Set by DemoService for agent-gateway message dump filenames. */
    __csActiveDemoKey?: string;
  }
}

if (typeof window !== 'undefined') {
  window.__csAgentGatewayMsgDebugDownload = downloadAgentGatewayMessageDump;
}
