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
 * Framework-agnostic gateway for agent sessions.
 *
 * Architecture (matching the react-example / new backend):
 *  - A single "global observer" WebSocket connects to /ws (no query params).
 *  - Agents are spawned via HTTP POST /api/v1/spawn; the backend assigns session IDs.
 *  - All agent messages arrive on the single observer socket.
 *  - Broadcasts are sent through the observer socket using BroadcastRequest.
 *
 * Consumers subscribe via onSessionsChange() / onChat() and receive plain data.
 */

import * as protobuf from 'protobufjs';
import {
  type AgentGatewayInboundRecord,
  type AgentGatewayOriginCapture,
  recordAgentGatewayInboundMessage,
} from '../../agent-gateway-message-dump';
import { AgentMessageType } from './types';
import { simLog } from './sim-logger';

// ── Types ────────────────────────────────────────────────────────────────────

/**
 * Implemented by the 3D runner manager so the gateway can control runners
 * directly without routing through window events or Angular.
 */
export interface RunnerController {
  setVelocity(guid: string, velocity: number): void;
  setWater(guid: string, water: number): void;
  setWorking(guid: string, working: boolean): void;
  setProgress?(guid: string, t: number): void;
  syncBackendProgress?(guid: string, progress: number, velocity: number): void;
  setCollapsed?(guid: string): void;
}

export interface BackendAgent {
  guid: string;
  agentType: string;
  /** Human-readable name from backend (e.g. "Cloud Marathon Planner"). */
  displayName: string;
  connected: boolean;
}

export interface ChatMessage {
  guid: string;
  speaker: string;
  text: string;
  isUser: boolean;
  timestamp: Date;
  msgType: AgentMessageType;
  title?: string;

  // Optional
  toolName?: string;
  skillName?: string;
  icon?: string;
  rawJson?: string;
  result?: any;
  simulationId?: string;
}

enum TOOLS {
  SHOW_ROUTE = 'report_marathon_route',
  LOAD_SKILL = 'load_skill',
  FINANCIAL_SECURITY = 'set_financial_modeling_mode',
  START_SIMULATION = 'start_simulation',
  SIMULATION_PIPELINE = 'simulation_pipeline',
  /** Kept in sync with `SIMULATION_GATEWAY_TOOL_NAMES` in `agent-gateway-message-dump.ts`. */
  PREPARE_SIMULATION = 'prepare_simulation',
  GET_LAWS = 'get_local_and_traffic_rules',
  SPAWN_RUNNERS = 'spawn_runners',
  START_RACE = 'fire_start_gun',
  ADVANCE_TICK = 'advance_tick',
  RUNNER_PROCESS_TICK = 'process_tick',
  CHECK_RACE_STATUS = 'check_race_complete',
  COMPILE_RESULTS = 'compile_results',
  A2UI = 'validate_and_emit_a2ui',
  TRAFFIC = 'assess_traffic_impact',
}

enum RACE_STATUS {
  IN_PROGRESS = 'in_progress',
  COMPLETE = 'race_complete',
}

type SessionsListener = (sessions: BackendAgent[]) => void;
type ChatListener = (msg: ChatMessage) => void;
type VoidListener = () => void;

/** Handles a single recognised key from an incoming JSON payload. */
type CommandHandler = (guid: string, value: unknown) => void;

type LoadSkillData = {
  tool_hints: {
    name: string;
  };
};
// ── Helpers ──────────────────────────────────────────────────────────────────
/**
 * Resolve the gateway WebSocket URL from runtime config (BFF), build-time
 * env, or localhost fallback.  The BFF serves /config.js which sets
 * window.ENV = { NG_APP_GATEWAY_URL: "/ws", NG_APP_GATEWAY_ADDR: "" }.
 * Relative paths like "/ws" are expanded to wss://host/ws.
 */
function resolveGatewayWsUrl(): string {
  const env = (window as any).ENV || {};
  const configured: string = env.NG_APP_GATEWAY_URL ?? import.meta.env.NG_APP_GATEWAY_URL ?? '';
  if (!configured) return 'ws://127.0.0.1:8101/ws';
  if (configured.startsWith('/')) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}${configured}`;
  }
  return configured;
}

/**
 * Resolve the gateway HTTP base URL from runtime config (BFF), build-time
 * env, or localhost fallback.  Returns an empty string when the BFF is
 * serving (meaning all API calls should use relative paths).
 */
function resolveGatewayHttpBase(): string {
  const env = (window as any).ENV || {};
  // Empty string from BFF means "use relative URLs" (BFF proxies /api/v1/*).
  // Build-time .env provides the absolute URL for local dev.
  return env.NG_APP_GATEWAY_ADDR ?? import.meta.env.NG_APP_GATEWAY_ADDR ?? '';
}

// ── AgentGateway ────────────────────────────────────────────────────────────

class AgentGateway {
  private Wrapper: protobuf.Type | null = null;
  private BroadcastRequest: protobuf.Type | null = null;

  private reconnectDelay = 2000;
  private readonly MAX_RECONNECT_DELAY = 30000;

  /** Single global observer WebSocket. */
  private monitorSocket: WebSocket | null = null;

  /** Agent sessions tracked locally (spawned via HTTP API). */
  private sessions = new Map<string, BackendAgent>();
  private seenRequests = new Set<string>();

  private sessionListeners: SessionsListener[] = [];
  private chatListeners: ChatListener[] = [];
  private controller: RunnerController | null = null;

  /** Optional hook so debug logs can compare backend tick counts to AgentScreen UI state. */
  private uiNumberOfFinishersGetter: (() => number) | null = null;

  /** Sessions currently inside a run (between run_start and run_end). */
  private workingSessions = new Set<string>();

  /**
   * Command registry: map a JSON key to a handler.
   * When an incoming message contains a JSON payload, every matching key
   * here fires its handler with (guid, value).
   */
  private readonly commands = new Map<string, CommandHandler>([
    [
      'velocity',
      (guid, value) => {
        if (typeof value !== 'number') return;
        this.controller?.setVelocity(guid, value);
      },
    ],
    [
      'water',
      (guid, value) => {
        if (typeof value !== 'number') return;
        this.controller?.setWater(guid, value);
      },
    ],
    [
      'distance',
      (guid, value) => {
        if (typeof value !== 'number') return;
        // Convert distance (meters) to normalized 0-1 progress. Marathon = 42195m.
        const t = Math.min(value / 42195, 1.0);
        this.controller?.setProgress?.(guid, t);
      },
    ],
    [
      'collapsed',
      (guid, value) => {
        if (value !== true) return;
        this.controller?.setCollapsed?.(guid);
      },
    ],
  ]);

  /** Pending tool call queue per session — used to match tool results with their tool names. */
  private pendingTools = new Map<string, string[]>();
  /** Last model text per session — used to deduplicate trailing narrative echoes. */
  private lastModelText = new Map<string, string>();
  /** Dedup key for route imports — prevents the same route from being imported twice. */
  private _lastRouteKey = '';
  /** Track runner sessions discovered from tick messages to auto-create 3D runners. */
  private _knownRunnerSessions = new Set<string>();
  /** Last function_call raw text per session — dedup duplicate model_end messages. */
  private lastFunctionCallText = new Map<string, string>();

  /** Simulation ID returned by the most recent start_simulation tool call. */
  private subscribedSimulationId: string | null = null;

  /** True while NDJSON replay is driving `handleMessage` — avoids clearing subscription on replayed `run_end` / duplicate WS subscribe on `model_start`. */
  private ndjsonReplayActive = false;

  private previousMessageIsA2ui: boolean = false;
  private previousMessageIsFinancialPlanner: boolean = false;

  private isSpinningUpSubAgent: boolean = false;
  private raceComplete: boolean = false;

  filterSettings = { showLoadSkills: false };

  private collapsedRunners = new Set<string>();
  /** Dedupe backend `runner_status === finished` (process_tick may repeat until race ends). */
  private finishedRunners = new Set<string>();

  /** After `fire_start_gun`, collect the first N `process_tick` effective velocities (N = runner_count). */
  private firstPaceSampleTarget = 0;
  private firstPaceVelocities: number[] = [];

  private userSpawnedAgents = new Set<string>();

  /**
   * Agent type from the user-spawned session (first resolved). Used so pipeline / sub-session
   * messages (same simulation, different origin.session_id) still show the main chat agent in UI.
   */
  private primaryChatAgentType: string | null = null;

  /** Demo agent key while cached NDJSON runs (spawn GUIDs won't match recorded session ids). */
  private replayPrimaryAgentTypeHint: string | null = null;

  setFilterSettings(settings: Partial<{ showLoadSkills: boolean }>): void {
    Object.assign(this.filterSettings, settings);
  }

  private emitSessions(): void {
    const sessions = this.getSessions();
    for (const fn of this.sessionListeners) fn(sessions);
  }

  constructor() {
    this.loadProto();
    // Listen for broadcast requests from the viewport to send RunnerEvents
    // window.addEventListener('sim:broadcastToRunner', (e: Event) => {
    //   const detail = (e as CustomEvent).detail as { sessionId: string; payload: string };
    //   if (detail?.sessionId && detail?.payload) {
    //     this.sendBroadcastNow(detail.payload, [detail.sessionId]);
    //   }
    // });
  }

  /** Register the 3D runner manager so commands reach runners directly. */
  setController(ctrl: RunnerController): void {
    this.controller = ctrl;
  }

  setUiNumberOfFinishersGetter(getter: (() => number) | null): void {
    this.uiNumberOfFinishersGetter = getter;
  }

  private async loadProto(): Promise<void> {
    try {
      const root = await protobuf.load('/gateway.proto');
      this.Wrapper = root.lookupType('gateway.Wrapper');
      this.BroadcastRequest = root.lookupType('gateway.BroadcastRequest');
      // Connect the monitor socket once proto is ready
      this.connectMonitor();
    } catch (e) {
      console.error('AgentGateway: proto load failed', e);
    }
  }

  // ── Monitor WebSocket ───────────────────────────────────────────────────────

  private connectMonitor(): void {
    const wsUrl = resolveGatewayWsUrl();
    console.debug('AgentGateway: connecting monitor to', wsUrl);

    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    this.monitorSocket = ws;

    ws.onopen = () => {
      if (this.subscribedSimulationId) {
        this._sendTextFrame({
          type: 'subscribe_simulation',
          simulation_id: this.subscribedSimulationId,
        });
      }
      this.reconnectDelay = 2000;
    };

    ws.onmessage = (evt) => {
      if (this.ndjsonReplayActive) return;
      this.handleMessage(evt);
    };

    ws.onclose = () => {
      const delay = this.reconnectDelay + Math.random() * 1000;
      console.warn(`AgentGateway: monitor disconnected — reconnecting in ${Math.round(delay)}ms`);
      this.monitorSocket = null;
      setTimeout(() => this.connectMonitor(), delay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.MAX_RECONNECT_DELAY);
    };

    ws.onerror = () => {
      console.error('AgentGateway: monitor connection error');
    };
  }

  // ── Subscriptions ──────────────────────────────────────────────────────────

  onSessionsChange(fn: SessionsListener): () => void {
    this.sessionListeners.push(fn);
    return () => {
      this.sessionListeners = this.sessionListeners.filter((l) => l !== fn);
    };
  }

  onChat(fn: ChatListener): () => void {
    this.chatListeners.push(fn);
    return () => {
      this.chatListeners = this.chatListeners.filter((l) => l !== fn);
    };
  }

  subscribeSimulation(simulationId: string): void {
    this.subscribedSimulationId = simulationId;

    this._sendTextFrame({ type: 'subscribe_simulation', simulation_id: simulationId });
  }
  unsubscribeSimulation(simulationId: string): void {
    if (this.subscribedSimulationId === simulationId) {
      this.subscribedSimulationId = null;
    }

    this._sendTextFrame({ type: 'unsubscribe_simulation', simulation_id: simulationId });
  }
  private _sendTextFrame(payload: object): void {
    if (this.monitorSocket?.readyState === WebSocket.OPEN) {
      this.monitorSocket.send(JSON.stringify(payload));
    } else {
      console.warn('AgentGateway: socket not open, cannot send text frame', payload);
    }
  }

  // ── Session management ─────────────────────────────────────────────────────

  async addAgent(agentType = 'runner_autopilot'): Promise<string> {
    try {
      const baseUrl = resolveGatewayHttpBase();
      const resp = await fetch(`${baseUrl}/api/v1/spawn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agents: [{ agentType, count: 1 }] }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(err.error || resp.statusText);
      }

      const result = await resp.json();
      const spawnedSessions = result.sessions || [];

      if (spawnedSessions.length === 0) {
        throw new Error('No sessions returned from spawn API');
      }

      const s = spawnedSessions[0];
      const sessionId = s.sessionId;
      this.userSpawnedAgents.add(sessionId);

      const info: BackendAgent = {
        guid: sessionId,
        agentType: s.agentType || agentType,
        displayName: '', // populated from proto Origin.display_name on first message
        connected: true,
      };
      this.sessions.set(sessionId, info);
      this.emitSessions();

      return sessionId;
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      this.emitChat({
        guid: 'system',
        speaker: 'system',
        text: `Spawn failed: ${errMsg}`,

        isUser: false,
        timestamp: new Date(),

        msgType: 'system',
      });
      throw e;
    }
  }

  removeAgent(guid: string): void {
    if (this.userSpawnedAgents.has(guid)) {
      this.userSpawnedAgents.delete(guid);
      this.primaryChatAgentType = null;
    }
    this.sessions.delete(guid);
    this.emitSessions();
  }

  getSessions(): BackendAgent[] {
    return Array.from(this.sessions.values());
  }

  hasSession(guid: string): boolean {
    return this.sessions.has(guid);
  }

  getSimulationId(): string | null {
    return this.subscribedSimulationId;
  }

  removeCurrentSimulationId(): void {
    if (this.subscribedSimulationId) {
      this.unsubscribeSimulation(this.subscribedSimulationId);
    }
    this.subscribedSimulationId = null;
  }

  // ── Broadcast ──────────────────────────────────────────────────────────────

  setSessionForReplay(sessionId: string, agentType: string) {
    const info: BackendAgent = {
      guid: sessionId,
      agentType: agentType,
      displayName: '', // populated from proto Origin.display_name on first message
      connected: true,
    };
    this.sessions.set(sessionId, info);
  }

  /**
   * Call before timed NDJSON replay: sets `subscribedSimulationId` from the dump and
   * enables replay mode so replayed `run_end` / `model_start` do not mutate live subscription state.
   */
  beginNdjsonReplay(): void {
    this.ndjsonReplayActive = true;
  }

  endNdjsonReplay(): void {
    this.ndjsonReplayActive = false;
    this.replayPrimaryAgentTypeHint = null;
  }

  /** True while timed NDJSON cached replay is active (see {@link beginNdjsonReplay}). */
  isNdjsonReplayActive(): boolean {
    return this.ndjsonReplayActive;
  }

  /**
   * While cached replay runs, recorded session UUIDs rarely match the live spawn id.
   * Set to the demo's agent key (e.g. `simulator_with_failure`) so chat labels match the demo bot.
   */
  setReplayPrimaryAgentTypeHint(agentType: string | null): void {
    this.replayPrimaryAgentTypeHint = agentType && agentType.length > 0 ? agentType : null;
  }

  /**
   * Builds wire-format `Wrapper` bytes from a thin NDJSON row so timed replay can call `handleMessage`
   * without `rawBase64` in the dump file (see `replayAgentGatewayMsgNdjsonText`).
   */
  encodeInboundRecordForReplay(rec: AgentGatewayInboundRecord): ArrayBuffer | null {
    if (!this.Wrapper) return null;
    let payloadBytes: Uint8Array;
    try {
      payloadBytes = new TextEncoder().encode(JSON.stringify(rec.data));
    } catch {
      return null;
    }
    const d = rec.data;
    const o = rec.origin;
    const simId =
      typeof d['simulation_id'] === 'string'
        ? d['simulation_id']
        : typeof d['simulationId'] === 'string'
          ? d['simulationId']
          : '';
    const sessFromData =
      typeof d['session_id'] === 'string'
        ? d['session_id']
        : typeof d['sessionId'] === 'string'
          ? d['sessionId']
          : '';
    const sess =
      o?.sessionId && o.sessionId.length > 0 ? o.sessionId : sessFromData || 'replay-session';
    const agentId =
      o?.id && o.id.length > 0 ? o.id : typeof d['agent'] === 'string' ? d['agent'] : 'planner';
    const originType = o?.type && o.type.length > 0 ? o.type : 'agent';
    const originOut: {
      type: string;
      id: string;
      sessionId: string;
      displayName?: string;
    } = {
      type: originType,
      id: agentId,
      sessionId: sess,
    };
    if (o?.displayName && o.displayName.length > 0) {
      originOut.displayName = o.displayName;
    }
    const meta: Record<string, unknown> = {};
    if (typeof rec.speaker === 'string' && rec.speaker.length > 0) {
      meta['_csReplaySpeaker'] = rec.speaker;
    }
    const metadataBytes =
      Object.keys(meta).length > 0 ? new TextEncoder().encode(JSON.stringify(meta)) : null;
    const wrapper = this.Wrapper.create({
      type: rec.wrapperType,
      event: rec.event,
      payload: payloadBytes,
      simulationId: simId || undefined,
      origin: originOut,
      metadata: metadataBytes && metadataBytes.length > 0 ? metadataBytes : undefined,
    });
    const fin = this.Wrapper.encode(wrapper).finish();
    return new Uint8Array(fin).buffer;
  }

  handleMessage(messageEvent: MessageEvent) {
    if (!this.Wrapper) return;

    try {
      const wrapper = this.Wrapper.decode(new Uint8Array(messageEvent.data)) as any;

      let replaySpeakerFromMeta: string | undefined;
      try {
        const md = wrapper.metadata as Uint8Array | undefined;
        if (md?.length) {
          const parsed = JSON.parse(new TextDecoder().decode(md)) as { _csReplaySpeaker?: string };
          if (typeof parsed._csReplaySpeaker === 'string' && parsed._csReplaySpeaker.length > 0) {
            replaySpeakerFromMeta = parsed._csReplaySpeaker;
          }
        }
      } catch {
        /* ignore */
      }

      const wrapperType: string = wrapper.type || '';
      const event: string = wrapper.event || '';

      const rawPayload: Uint8Array | null = wrapper.payload?.length ? wrapper.payload : null;
      const decodedText = rawPayload ? new TextDecoder().decode(rawPayload) : '';
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(decodedText);
      } catch {
        /* ignore */
      }

      // Skip broadcast echoes (messages we sent)
      if (event === 'broadcast') return;

      simLog.log(
        'recv',
        wrapper.origin?.sessionId || '?',
        `type=${wrapperType} event=${event} payload=${new TextDecoder().decode(wrapper.payload ?? new Uint8Array())}`,
      );

      // Resolve session identity from origin (preferred) or legacy fields
      const origin = wrapper.origin || {};
      const sessionId: string =
        origin.sessionId || origin.session_id || wrapper.sessionId || wrapper.session_id || '';

      // Look up session for display metadata, auto-registering unknown
      // sessions from the protobuf origin field. On GCP, Agent Engine
      // agents create their own session IDs that differ from the spawn
      // API's session IDs, so events arrive from sessions the frontend
      // never explicitly spawned. Scoped to the current simulation to
      // prevent cross-simulation "bleed".
      let session = this.sessions.get(sessionId);
      // protobufjs camelCases snake_case field names
      const displayName: string = origin.displayName || origin.display_name || '';

      if (
        !session &&
        sessionId &&
        (this.ndjsonReplayActive ||
          (this.subscribedSimulationId && wrapper.simulationId === this.subscribedSimulationId))
      ) {
        const inferredType =
          (typeof origin.id === 'string' && origin.id.length > 0 && origin.id !== 'agent'
            ? origin.id
            : null) ??
          (typeof origin.type === 'string' && origin.type.length > 0 && origin.type !== 'agent'
            ? origin.type
            : null) ??
          'unknown';

        session = {
          guid: sessionId,
          agentType: inferredType,
          displayName,
          connected: true,
        };
        this.sessions.set(sessionId, session);
        this.emitSessions();
      }

      // Update display name from proto origin if we didn't have one yet
      if (session && displayName && !session.displayName) {
        session.displayName = displayName;
        this.emitSessions();
      }

      if (sessionId && this.userSpawnedAgents.has(sessionId) && session) {
        this.primaryChatAgentType = session.agentType;
      }

      const isUserSpawned = Boolean(sessionId && this.userSpawnedAgents.has(sessionId));
      const roleFromOrigin =
        typeof origin.id === 'string' && origin.id.length > 0 && origin.id !== 'agent'
          ? origin.id
          : '';
      const roleFromPayload =
        typeof data['agent'] === 'string' && data['agent'].length > 0
          ? (data['agent'] as string)
          : '';

      let roleForSpeaker: string;
      if (isUserSpawned && session) {
        roleForSpeaker = session.agentType;
      } else {
        roleForSpeaker =
          this.primaryChatAgentType ||
          this.replayPrimaryAgentTypeHint ||
          roleFromPayload ||
          roleFromOrigin ||
          session?.agentType ||
          'agent';
      }

      const label = session?.displayName || displayName || roleForSpeaker;
      const speaker = replaySpeakerFromMeta ?? `${label} (${sessionId.substring(0, 6)})`;

      const skillName = (data as LoadSkillData)['tool_hints']?.name;

      const isRunner = origin.id === 'runner_autopilot';
      const isRunnerProcessTickToolEnd =
        wrapperType === 'json' &&
        event === 'tool_end' &&
        data['tool_name'] === TOOLS.RUNNER_PROCESS_TICK;

      if (isRunner && !isRunnerProcessTickToolEnd) {
        return;
      }

      if (origin.id === 'tick' && event !== 'tool_end') {
        return;
      }

      if (
        !this.ndjsonReplayActive &&
        this.subscribedSimulationId &&
        wrapper.simulationId !== this.subscribedSimulationId
      ) {
        return;
      }

      if (!this.ndjsonReplayActive && !this.subscribedSimulationId && !session) {
        // Drop messages from unknown sessions when no simulation is active.
        // Do NOT call unsubscribeSimulation here — the simulation_id on
        // this message may be reused later by start_simulation, and
        // unsubscribing it now would cause the Hub to stop delivering
        // all future messages for that simulation (e.g., simulator
        // internal events during verify leak through before the frontend
        // subscribes, poisoning the simulation_id for the later execute).
        // this.unsubscribeSimulation(wrapper.simulationId);
        return;
      }

      if (!this.subscribedSimulationId && session) {
        // console.log('**** where else is this issue happening??');
        // this.unsubscribeSimulation(wrapper.simulationId);
      }

      if (!this.ndjsonReplayActive) {
        const captureOrigin: AgentGatewayOriginCapture = {
          id:
            session?.agentType ||
            (typeof origin.id === 'string' ? origin.id : '') ||
            (typeof origin.type === 'string' ? origin.type : '') ||
            'unknown',
        };
        if (typeof origin.type === 'string' && origin.type.length > 0) {
          captureOrigin.type = origin.type;
        }
        if (sessionId.length > 0) {
          captureOrigin.sessionId = sessionId;
        }
        const capturedDisplay = session?.displayName || displayName;
        if (capturedDisplay.length > 0) {
          captureOrigin.displayName = capturedDisplay;
        }
        recordAgentGatewayInboundMessage({
          timestamp: wrapper.timestamp,
          wrapperType,
          event,
          data,
          origin: captureOrigin,
          speaker,
        });
      }

      // console.log({
      //   wrapper,
      //   wrapperType,
      //   origin,
      //   data,
      //   displayName,
      //   session,
      // });

      switch (wrapperType) {
        // ── JSON events ──────────────────────────────────────────────────────
        // payload: structured JSON dict
        case 'json': {
          switch (event) {
            case 'run_start':
              this.emitChat({
                guid: sessionId,
                speaker: speaker,
                text: 'run start',
                isUser: false,
                timestamp: new Date(),
                msgType: AgentMessageType.RUN_START,
              });
              return;
            case 'run_end':
              if (session && this.userSpawnedAgents.has(sessionId) && !this.ndjsonReplayActive) {
                this.unsubscribeSimulation(this.subscribedSimulationId as string);
                this.removeCurrentSimulationId();
              }

              this.emitChat({
                guid: sessionId,
                speaker: speaker,
                text: 'run end',
                isUser: false,
                timestamp: new Date(),
                msgType: AgentMessageType.RUN_END,
              });
              return;
            case 'marathon_route_final':
              console.warn('MARATHON_ROUTE_FINAL call removed.');

              return;
            case 'tool_start': {
              const toolName = data['tool'];

              switch (toolName) {
                case TOOLS.LOAD_SKILL:
                  if (!this.filterSettings.showLoadSkills) return;

                  break;
                case TOOLS.SIMULATION_PIPELINE:
                  return;
                case TOOLS.A2UI:
                  return;
                // case TOOLS.SHOW_ROUTE:
                //   return;
              }

              this.emitChat({
                guid: sessionId,
                speaker: speaker,
                text: '',
                isUser: false,
                timestamp: new Date(),
                msgType: AgentMessageType.TOOL_START,
                toolName: toolName as string,
                skillName: skillName || '',
              });

              return;
            }
            case 'tool_result':
              console.warn('missing :: telemetry tool_result', data);
              // Before a tool call is executed
              return;

            case 'tool_end': {
              const result = data['result'] as {
                message: string;
                status: string;
                simulation_id?: string;
                simulationId?: string;
                session_ids?: string[];
                runner_count?: number;
                velocity?: number;
                effective_velocity?: number;
                water?: number;
                distance_km?: number;
                distance_mi?: number;
                exhausted?: boolean;
                collapsed?: boolean;
                skill_name?: string;
                runner_status?: string;
                status_counts?: any;
              };
              const toolName = data['tool_name'];

              if (!result || !toolName) return;

              switch (toolName) {
                case TOOLS.LOAD_SKILL:
                  if (!this.filterSettings.showLoadSkills) return;
                  break;
                case TOOLS.SHOW_ROUTE:
                  window.dispatchEvent(
                    new CustomEvent('gateway:routeGeojson', { detail: { geojson: result } }),
                  );
                  break;
                case TOOLS.FINANCIAL_SECURITY:
                  return;
                case TOOLS.TRAFFIC: {
                  const affectedIntersections = (result as any)['affected_intersections'];
                  const affectedSegments = (result as any)['affected_segments'];
                  const closedSegments = (result as any)['closed_segments'];
                  // if (Array.isArray(intersections) && intersections.length > 0) {
                  window.dispatchEvent(
                    new CustomEvent('gateway:trafficZones', {
                      detail: {
                        affectedIntersections,
                        affectedSegments,
                        closedSegments,
                      },
                    }),
                  );
                  // }
                  break;
                }

                case TOOLS.START_SIMULATION:
                  if (!this.subscribedSimulationId && wrapper.simulationId) {
                    this.subscribeSimulation(wrapper.simulationId as string);
                    this.raceComplete = false;
                  }
                  break;
                case TOOLS.GET_LAWS:
                  this.emitChat({
                    guid: sessionId,
                    speaker: speaker,

                    text: result.message,

                    isUser: false,
                    timestamp: new Date(),
                    msgType: AgentMessageType.TOOL_END,
                    toolName: data['tool_name'] as string,
                    result,
                  });
                  return;
                case TOOLS.SPAWN_RUNNERS: {
                  const sessionIds = result['session_ids'] as string[] | undefined;
                  if (Array.isArray(sessionIds)) {
                    for (const runnerId of sessionIds) {
                      // Register runner in session map for display metadata
                      if (!this.sessions.has(runnerId)) {
                        this.sessions.set(runnerId, {
                          guid: runnerId,
                          agentType: 'runner_autopilot',
                          displayName: '',
                          connected: true,
                        });
                      }

                      // Track for tick routing. Always dispatch: viewport dedupes re-delivery / same
                      // guid via runnerManager.getRunner (early return if mesh already exists).
                      this._knownRunnerSessions.add(runnerId);
                      window.dispatchEvent(
                        new CustomEvent('hud:addSimRunner', {
                          detail: {
                            guid: `sim-${runnerId}`,

                            velocity: 0,
                            distanceMi: 0,
                            progress: 0,
                          },
                        }),
                      );
                    }
                    this.emitSessions();
                  }
                  break;
                }
                case TOOLS.START_RACE: {
                  const rc = result['runner_count'] as number | undefined;
                  this.firstPaceSampleTarget = typeof rc === 'number' && rc > 0 ? rc : 0;
                  this.firstPaceVelocities = [];

                  this.emitChat({
                    guid: sessionId,
                    speaker: speaker,

                    text: result.message,

                    isUser: false,
                    timestamp: new Date(),
                    msgType: AgentMessageType.TOOL_END,
                    toolName: data['tool_name'] as string,
                    result,
                  });
                  return;
                }
                case TOOLS.ADVANCE_TICK:
                  console.log('advance tick', data, result);
                  if (this.raceComplete) return;
                  this.emitChat({
                    guid: sessionId,
                    speaker: speaker,

                    text: result.message,
                    result,

                    isUser: false,
                    timestamp: new Date(),
                    msgType: AgentMessageType.TOOL_END,
                    toolName: data['tool_name'] as string,
                  });
                  return;
                case TOOLS.RUNNER_PROCESS_TICK:
                  const velocity = result['velocity'] as number;
                  const effectiveVelocity = (result['effective_velocity'] as number) ?? velocity;
                  const water = result['water'] as number;

                  if (
                    this.firstPaceSampleTarget > 0 &&
                    this.firstPaceVelocities.length < this.firstPaceSampleTarget
                  ) {
                    this.firstPaceVelocities.push(effectiveVelocity);
                    if (this.firstPaceVelocities.length === this.firstPaceSampleTarget) {
                      const sum = this.firstPaceVelocities.reduce((a, b) => a + b, 0);
                      const avg = sum / this.firstPaceVelocities.length;
                      window.dispatchEvent(
                        new CustomEvent('sim:firstBatchAvgVelocity', {
                          detail: { avgVelocity: avg },
                        }),
                      );
                    }
                  }

                  // window.dispatchEvent(
                  //   new CustomEvent('sim:eventLog', {
                  //     detail: {
                  //       guid: `sim-${sessionId}`,
                  //       type: 'in',
                  //       message: `v=${velocity} ev=${effectiveVelocity} w=${water}%`,
                  //     },
                  //   }),
                  // );
                  window.dispatchEvent(
                    new CustomEvent('hud:updateSimRunner', {
                      detail: {
                        guid: `sim-${sessionId}`,
                        velocity: effectiveVelocity,
                        water,
                        _fromGateway: true,
                      },
                    }),
                  );

                  // ── Runner events: detect water station, rehydration, exhaustion, collapse ─
                  if (sessionId && this._knownRunnerSessions.has(sessionId)) {
                    if (result['exhausted']) {
                      // console.log('exhausted event', sessionId);
                      window.dispatchEvent(
                        new CustomEvent('sim:runnerEvent', {
                          detail: { guid: `sim-${sessionId}`, event: 'exhausted' },
                        }),
                      );
                    }
                    if (result['collapsed'] && !this.collapsedRunners.has(sessionId)) {
                      console.log('collapse event', sessionId);
                      window.dispatchEvent(
                        new CustomEvent('sim:runnerEvent', {
                          detail: { guid: `sim-${sessionId}`, event: 'collapsed' },
                        }),
                      );
                      this.collapsedRunners.add(sessionId);
                    }
                    if (
                      result['runner_status'] === 'finished' &&
                      !this.finishedRunners.has(sessionId)
                    ) {
                      this.finishedRunners.add(sessionId);
                      window.dispatchEvent(
                        new CustomEvent('sim:runnerEvent', {
                          detail: { guid: `sim-${sessionId}`, event: 'finished' },
                        }),
                      );
                    }
                  }

                  ///

                  return;
                case TOOLS.CHECK_RACE_STATUS:
                  if (result.status === RACE_STATUS.COMPLETE) {
                    this.raceComplete = true;
                    window.dispatchEvent(new CustomEvent('sim:finished'));
                  }
                  break;
                case TOOLS.COMPILE_RESULTS:
                  console.log(
                    'todo ;; so here should be passed to agent? but also what about a2ui version of this...',
                    { data, result },
                  );
                  break;
                case 'stop_race_collector':
                  // console.log('stop_race_collector here', { data, result });
                  break;
                default:
                  console.warn('!! WARN !!, no case for tool', { event, toolName });
              }

              this.emitChat({
                guid: sessionId,
                speaker: speaker,

                text: result.message,

                isUser: false,
                timestamp: new Date(),
                msgType: AgentMessageType.TOOL_END,
                toolName: data['tool_name'] as string,
                skillName: result['skill_name'],
              });

              return;
            }

            case 'tool_error':
              this.emitChat({
                guid: sessionId,
                speaker,

                isUser: false,
                timestamp: new Date(),

                msgType: AgentMessageType.TOOL_ERROR,
                toolName: data['tool_name'] as string,
                text: `${data['text']}`,
              });
              break;

            case 'model_start':
              if (!this.subscribedSimulationId && wrapper.simulationId) {
                this.subscribedSimulationId = wrapper.simulationId as string; // result['simulation_id'] as string;
                if (!this.ndjsonReplayActive) {
                  this.subscribeSimulation(this.subscribedSimulationId);
                }
                this.isSpinningUpSubAgent = false;
              }

              return;
            case 'model_end':
              break;

            case 'json':
              const result = data['result'] as {
                financial_modeling_mode?: any;
              };

              // Handle set_financial_modeling_mode wrapped in tool_name envelope
              if (
                data['tool_name'] === 'set_financial_modeling_mode' &&
                result['financial_modeling_mode']
              ) {
                this.emitChat({
                  guid: sessionId,
                  speaker: speaker,
                  isUser: false,
                  timestamp: new Date(),
                  toolName: 'set_financial_modeling_mode',
                  msgType: AgentMessageType.TOOL_END,
                  text: JSON.stringify(data['result']),
                });
                return;
              }

              if (data['tool_name']) return;
              if (!data['event_plan'] && !data['financial_modeling_mode']) return;

              // Legacy: top-level financial_modeling_mode (pre-envelope format)
              if (data['financial_modeling_mode']) {
                this.emitChat({
                  guid: sessionId,
                  speaker: speaker,
                  isUser: false,
                  timestamp: new Date(),
                  toolName: 'set_financial_modeling_mode',
                  msgType: AgentMessageType.TOOL_END,
                  text: JSON.stringify(data),
                });
                return;
              }

              this.emitChat({
                guid: sessionId,
                speaker: speaker,
                isUser: false,
                timestamp: new Date(),
                msgType: AgentMessageType.TOOL_END,
                text: JSON.stringify(data),
              });
              // Generic parsed JSON from agent output (RedisOrchestratorDispatcher)
              break;

            case 'inter-agent':
              this.isSpinningUpSubAgent = true;

              break;

            case 'tick:advance':
              break;
            case 'text':
              if (!this.previousMessageIsA2ui && !this.previousMessageIsFinancialPlanner) {
                this.emitChat({
                  guid: sessionId,
                  speaker: speaker,
                  isUser: false,
                  timestamp: new Date(),
                  msgType: AgentMessageType.TEXT,
                  text: `${data['text']}`,
                });
              } else {
                console.warn('Warning previous message was marked as a2ui so swallowed message: ', {
                  data,
                  wrapper,
                  event,
                });
              }

              break;
            default:
              console.log('no case for ', event);
          }
          break;
        }

        // ── A2UI events ──────────────────────────────────────────────────────
        // payload: A2UI JSON object (surfaceUpdate / dataModelUpdate / etc.)
        case 'a2ui': {
          console.log('a2ui', data);
          this.emitChat({
            guid: sessionId,
            speaker: speaker,
            isUser: false,
            timestamp: new Date(),
            msgType: AgentMessageType.TOOL_END,
            result: data,
            text: '',
          });

          // event is always "a2ui"
          // payload is the A2UI object — beginRendering | surfaceUpdate |
          //   dataModelUpdate | deleteSurface
          break;
        }
        // ── Text events ──────────────────────────────────────────────────────
        // payload: { "text": "<string>" }
        case 'text': {
          switch (event) {
            case 'tool_start':
              console.warn('missing :: text tool_start', decodedText);
              // After a tool returns a non-JSON text result
              // payload: { "text": "[Agent] Tool End: <tool>\n\n<result>" }
              break;
            case 'tool_end':
              console.warn('missing :: text tool_end', decodedText);
              // After a tool returns a non-JSON text result
              // payload: { "text": "[Agent] Tool End: <tool>\n\n<result>" }
              break;
            case 'tool_error':
              console.warn('missing :: text tool_error', decodedText);
              // When a tool call raises an exception
              // payload: { "text": "[Agent] Tool Error: <tool>\n\nError: <msg>" }
              break;

            case 'model_start':
              console.warn('missing :: text model_start', decodedText);
              // After an LLM call completes (turn_complete=true)
              // payload: { "text": "[Agent] Model End\n\n<response>" }
              break;

            case 'model_end':
              console.warn('missing :: text model_end', decodedText);
              // After an LLM call completes (turn_complete=true)
              // payload: { "text": "[Agent] Model End\n\n<response>" }
              break;
            case 'model_error':
              console.warn('missing :: text model_error', decodedText);
              // When an LLM call fails
              // payload: { "text": "[Agent] Model Error\n\nError: <msg>" }
              break;

            case 'text':
              console.warn('missing :: text text', decodedText);
              // Plain text from RedisOrchestratorDispatcher runner events
              // payload: { "text": "<agent output>" }
              break;
          }
          break;
        }

        // ── Telemetry events ─────────────────────────────────────────────────
        // payload: full plugin payload dict — always includes session_id,
        //          invocation_id, seq (monotonic per-session sequence number)
        case 'telemetry': {
          console.warn('Missing : telemetry event -> ', event);
          break;
        }

        // ── Environment reset ────────────────────────────────────────────────
        // Broadcast to ALL clients after POST /api/v1/environment/reset.
        // Each RedisOrchestratorDispatcher cancels background tasks, clears
        // active sessions, dedup caches, and the simulation registry.
        case 'environment_reset': {
          console.warn('missing :: environment_reset');
          break;
        }
        default:
          console.error('no case for ', wrapperType);
      }
    } catch (e) {
      console.error('error with', e);
    }
  }

  emitChat(message: ChatMessage) {
    if (!message.rawJson) {
      try {
        message.rawJson = JSON.stringify(
          message,
          (_k, v) => (v instanceof Date ? v.toISOString() : v),
          2,
        );
      } catch {
        /* ignore circular refs */
      }
    }
    for (const fn of this.chatListeners) fn(message);

    this.previousMessageIsA2ui =
      message.msgType === AgentMessageType.TOOL_END &&
      message.result &&
      (message.result['beginRendering'] || message.result['surfaceUpdate']);

    this.previousMessageIsFinancialPlanner =
      message.msgType === AgentMessageType.TOOL_END &&
      message.toolName === 'set_financial_modeling_mode';
  }

  // ── Broadcast ──────────────────────────────────────────────────────────────

  sendBroadcast(text: string, targetGuids: string[], silent = false): void {
    if (!this.Wrapper || !this.BroadcastRequest) {
      console.warn('AgentGateway: proto not ready');
      return;
    }
    if (targetGuids.length === 0) return;

    this.sendBroadcastNow(text, targetGuids);
    if (!silent) {
      this.emitChat({
        guid: '',
        speaker: 'You',
        isUser: true,
        msgType: AgentMessageType.SYSTEM,

        text,
        title: `${text.split(' ').slice(0, 3).join(' ')}...`,
        timestamp: new Date(),
      });
    }
  }

  /** Actually encode and send a broadcast over the wire. */
  private sendBroadcastNow(text: string, targetGuids: string[]): void {
    if (!this.Wrapper || !this.BroadcastRequest) return;

    let jsonPayload: unknown;
    try {
      jsonPayload = JSON.parse(text);
    } catch {
      jsonPayload = { text };
    }

    const innerPayload = new TextEncoder().encode(JSON.stringify(jsonPayload));
    const broadcastReq = this.BroadcastRequest.create({
      payload: innerPayload,
      targetSessionIds: targetGuids,
    });
    const brBinary = this.BroadcastRequest.encode(broadcastReq).finish();

    const wrapper = this.Wrapper.create({
      origin: { type: 'client', id: 'tester-ui', sessionId: 'tester-ui' },
      destination: targetGuids,
      status: 'success',
      type: 'broadcast',
      event: 'broadcast',
      payload: brBinary,
    });
    const binary = this.Wrapper.encode(wrapper).finish();

    if (this.monitorSocket && this.monitorSocket.readyState === WebSocket.OPEN) {
      simLog.log('send', targetGuids.join(','), `broadcast payload=${JSON.stringify(jsonPayload)}`);
      this.monitorSocket.send(binary);
    } else {
      console.warn('AgentGateway: monitor socket not connected');
    }
  }
}

// ── Singleton export ──────────────────────────────────────────────────────────

export const agentGateway = new AgentGateway();
