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

import { DateTime } from "luxon";
import "./index.css";
import { renderA2UI } from "./a2ui";
import { wsToHttp } from "./url";
import { createLogBuffer } from "./logBuffer";

import protobuf from "protobufjs";

// --- Types & Globals ---
interface SessionState {
  agentType: string;
}

const activeSessions = new Map<string, SessionState>();
let monitorSocket: WebSocket | null = null;
let logBuffer: ReturnType<typeof createLogBuffer>;

// --- Protobuf Initialization ---
let Wrapper: any;
let BroadcastRequest: any;
let A2UIAction: any;

async function initProto() {
  const root = await protobuf.load("/gateway.proto");
  Wrapper = root.lookupType("gateway.Wrapper");
  BroadcastRequest = root.lookupType("gateway.BroadcastRequest");
  A2UIAction = root.lookupType("gateway.A2UIAction");
}

// --- DOM Helpers ---
const app = document.getElementById("app")!;
const gatewayInput = () =>
  document.getElementById("gateway-url") as HTMLInputElement;
const sessionList = () => document.getElementById("session-list")!;
const logsContainer = () => document.getElementById("logs")!;
const broadcastPayload = () =>
  document.getElementById("broadcast-payload") as HTMLTextAreaElement;
const logFilterInput = () =>
  document.getElementById("log-filter") as HTMLInputElement;
const sessionSearchInput = () =>
  document.getElementById("session-search") as HTMLInputElement;

// --- Auto-scroll State ---
let userIsNearBottom = true;
const SCROLL_THRESHOLD = 80;

function isNearBottom(container: HTMLElement): boolean {
  return (
    container.scrollHeight - container.scrollTop - container.clientHeight <
    SCROLL_THRESHOLD
  );
}

function maybeAutoScroll() {
  const container = logsContainer();
  if (container && userIsNearBottom) {
    container.scrollTop = container.scrollHeight;
  }
}

// --- Utility Functions ---
function hashToHsl(str: string, s = 70, l = 50) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const h = Math.abs(hash) % 360;
  return `hsl(${h}, ${s}%, ${l}%)`;
}

function log(
  msg: string,
  type: "info" | "err" | "send" | "recv" = "info",
  meta?: {
    originId?: string;
    originType?: string;
    destination?: string[];
    rawMessage?: any;
  },
) {
  const container = logsContainer();
  if (!container) return;

  const filter = logFilterInput()?.value.toLowerCase();
  if (filter && !msg.toLowerCase().includes(filter)) return;

  const entry = document.createElement("div");
  entry.className =
    "p-3 rounded-xl border border-slate-800/50 bg-slate-900/40 text-[10px] font-mono flex flex-col gap-1.5 group shrink-0";

  const time = DateTime.now().toFormat("HH:mm:ss");
  const colorClass =
    type === "err"
      ? "text-red-400"
      : type === "send"
        ? "text-indigo-400"
        : type === "recv"
          ? "text-emerald-400"
          : "text-slate-500";
  const label = type.toUpperCase();

  let targetTags = "";
  if (meta?.destination && meta.destination.length > 0) {
    targetTags = meta.destination
      .map(
        (t) =>
          `<span class="px-1.5 py-0.5 bg-indigo-500/10 border border-indigo-500/20 rounded text-[8px] text-indigo-300 font-bold truncate max-w-[80px]" title="${t}">${t.substring(0, 8)}</span>`,
      )
      .join("");
  }

  const originId = meta?.originId
    ? `<span class="px-1.5 py-0.5 bg-slate-800 rounded text-slate-400 font-bold truncate max-w-[80px]" title="${meta.originId}">${meta.originId.substring(0, 8)}</span>`
    : "";
  const originType = meta?.originType
    ? `<span class="text-[8px] text-slate-500 font-bold uppercase tracking-widest">${meta.originType}</span>`
    : "";

  let rawJsonToggle = "";
  if (meta?.rawMessage) {
    const rawId = `raw-${Math.random().toString(36).substring(7)}`;
    rawJsonToggle = `
      <div class="mt-2 border-t border-slate-800/50 pt-2">
        <button onclick="document.getElementById('${rawId}').classList.toggle('hidden')" class="text-[8px] font-bold text-slate-500 hover:text-indigo-400 uppercase tracking-widest flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>
          Raw JSON
        </button>
        <div id="${rawId}" class="hidden mt-2 p-2 bg-slate-950 rounded border border-slate-800 text-[9px] text-slate-400 overflow-x-auto">
          <pre>${JSON.stringify(meta.rawMessage, null, 2)}</pre>
        </div>
      </div>
    `;
  }

  entry.innerHTML = `
        <div class="flex items-center gap-2 flex-wrap">
            <span class="text-slate-600 font-bold shrink-0">${time}</span>
            <span class="${colorClass} font-black tracking-widest shrink-0">${label}</span>
            <div class="flex items-center gap-1.5 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                ${originType} ${originId}
            </div>
            ${meta?.destination && meta.destination.length > 0 ? `<svg class="w-3 h-3 text-slate-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"></path></svg><div class="flex gap-1 flex-wrap">${targetTags}</div>` : ""}
        </div>
        <div class="text-slate-300 leading-relaxed break-words overflow-x-auto whitespace-pre-wrap">${msg}</div>
        ${rawJsonToggle}
    `;

  logBuffer.append(entry);
}

// --- Service Catalog ---
async function refreshCatalog() {
  try {
    const list = document.getElementById("agent-catalog-list")!;
    list.innerHTML =
      '<div class="py-4 text-center text-slate-500 animate-pulse text-[10px] font-bold uppercase tracking-widest">Scanning Catalog...</div>';

    const baseUrl = wsToHttp(gatewayInput().value);
    const resp = await fetch(`${baseUrl}/api/v1/agent-types`);
    const catalog = await resp.json();

    list.innerHTML = Object.keys(catalog)
      .map(
        (agent: string) => `
        <div class="p-3 rounded-xl bg-slate-900/40 border border-slate-800 hover:border-indigo-500/30 transition-all flex items-center justify-between group text-slate-200">
            <div class="flex flex-col">
                <span class="text-[10px] font-black text-indigo-400 uppercase tracking-widest">${agent.replace("_agent", "")}</span>
                <span class="text-[8px] text-slate-500 font-bold uppercase tracking-tighter">v1.2.5 • GENAI_3.0</span>
            </div>
            <div class="flex items-center gap-2">
                <input type="number" class="spawn-count-input w-8 bg-slate-950 border border-slate-800 rounded text-[10px] text-center font-bold py-0.5 focus:border-indigo-500 outline-none text-slate-200" value="1" min="1" max="10" />
                <button class="spawn-btn p-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-all shadow-lg" data-type="${agent}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                </button>
            </div>
        </div>
    `,
      )
      .join("");
  } catch (e) {
    log(`Failed to refresh catalog: ${e}`, "err");
  }
}

// --- Monitor WebSocket ---
function connectMonitor() {
  const baseUrl = gatewayInput().value;
  const wsUrl = `${baseUrl}`;
  log(`Connecting monitor to ${wsUrl}`, "info");

  const ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";
  monitorSocket = ws;

  ws.onopen = () => {
    log("Monitor connected — receiving all gateway messages", "info");
  };

  ws.onmessage = async (evt) => {
    if (!(evt.data instanceof ArrayBuffer)) return;

    try {
      const uint8 = new Uint8Array(evt.data);
      const wrapper = Wrapper.decode(uint8) as any;

      let data: any = {};
      if (wrapper.payload && wrapper.payload.length > 0) {
        try {
          const txt = new TextDecoder().decode(wrapper.payload);
          data = JSON.parse(txt);
        } catch {
          data = { text: new TextDecoder().decode(wrapper.payload) };
        }
      }

      const msg = {
        origin: wrapper.origin || {
          type: "system",
          id: "unknown",
          session_id: "",
        },
        destination: wrapper.destination || [],
        status: wrapper.status,
        event: wrapper.event,
        data: data,
        ...(wrapper.simulationId
          ? { simulationId: wrapper.simulationId }
          : {}),
      };

      if (
        msg.event === "narrative" || 
        msg.event === "text" || 
        msg.event === "json" || 
        msg.event === "a2ui" ||
        msg.event === "tool_start" ||
        msg.event === "tool_end" ||
        msg.event === "model_end" ||
        msg.event === "model_error" ||
        msg.event === "tool_error"
      ) {
        const pulse = msg.data;
        const targetSessionId =
          msg.origin.sessionId || msg.origin.session_id || "unknown";
        const sessionInfo = activeSessions.get(targetSessionId);

        // Priority: origin.id > activeSessions lookup > raw session ID
        let speaker: string;
        const originId = msg.origin.id;
        if (originId && originId !== "unknown") {
          speaker = originId.replace(/_/g, " ").toUpperCase();
        } else if (sessionInfo) {
          speaker = `${sessionInfo.agentType} (${targetSessionId.substring(0, 4)})`;
        } else {
          speaker = targetSessionId;
        }

        const sessionColor = hashToHsl(targetSessionId, 70, 50);
        let dataToSearch = pulse?.text;
        if (dataToSearch === undefined && pulse && typeof pulse === "object") {
          dataToSearch = JSON.stringify(pulse, null, 2);
        }
        dataToSearch = dataToSearch || "";

        try {
          const parsed = JSON.parse(dataToSearch);
          dataToSearch =
            typeof parsed === "object" && parsed.result && msg.event !== "tool_end"
              ? (typeof parsed.result === "string" ? parsed.result : JSON.stringify(parsed.result, null, 2))
              : dataToSearch;
        } catch (e) {
          /* not JSON */
        }

        const a2uiRegex = /(```a2ui\n|a2ui\n|a2ui\s?\{)([\s\S]*?)(?:\n```|$)/g;
        const a2uiMatches = [...dataToSearch.matchAll(a2uiRegex)];
        const a2uiElements: HTMLElement[] = [];
        let cleanText = dataToSearch;

        // Natively render the payload if it successfully came across the wire as an A2UI structured event
        if (msg.event === "a2ui" && pulse && typeof pulse === "object") {
          try {
            const a2uiEl = renderA2UI(pulse, {
              components: {},
              color: sessionColor,
              sessionId: targetSessionId,
              onAction: (action) => {
                sendA2UIAction(targetSessionId, action.name);
              },
            });
            if (a2uiEl) a2uiElements.push(a2uiEl);
          } catch (e) {
            console.error("[Tester] Native A2UI Parse Error:", e);
          }
        }

        for (const match of a2uiMatches) {
          const prefix = match[1];
          let rawJson = match[2].trim();
          if (prefix.endsWith("{") && !rawJson.startsWith("{")) {
            rawJson = "{" + rawJson;
          }
          cleanText = cleanText.replace(match[0], "\n```json\n" + rawJson + "\n```\n").trim();

          try {
            const data = JSON.parse(rawJson);
            const a2uiEl = renderA2UI(data, {
              components: {},
              color: sessionColor,
              sessionId: targetSessionId,
              onAction: (action) => {
                sendA2UIAction(targetSessionId, action.name);
              },
            });
            if (a2uiEl) a2uiElements.push(a2uiEl);
          } catch (e) {
            console.error("[Tester] A2UI Parse Error:", e);
          }
        }

        const isA2UI = a2uiElements.length > 0;
        const metadataTriggers = [
          "tool end",
          "model end",
          "task end",
          "run start",
          "run end",
        ];
        const lowerText = cleanText.toLowerCase();

        if (isA2UI && metadataTriggers.some((t) => lowerText.includes(t))) {
          const lines = cleanText.split("\n");
          if (lines.length > 2) cleanText = lines.slice(2).join("\n").trim();
          else if (lines.length <= 2) cleanText = "";
        }

        if (cleanText) {
          const technicalPattern =
            /(?:<ctrl42>call:|function_call=|args=\{)[\s\S]+?(?=\n\n|\n\[|$)/g;
          cleanText = cleanText.replace(technicalPattern, (match: string) => {
            return "\n```python\n" + match.trim() + "\n```\n";
          });

          // Wrap entire text in json if it's a raw json object that isn't already inside a code block
          if (
            (msg.event === "json" || msg.event === "a2ui" || msg.event === "tool_end" || msg.event === "model_error" || msg.event === "tool_error") &&
            !cleanText.includes("```json") &&
            (cleanText.trim().startsWith("{") || cleanText.trim().startsWith("["))
          ) {
              try {
                  const p = JSON.parse(cleanText);
                  cleanText = "\n```json\n" + JSON.stringify(p, null, 2) + "\n```\n";
              } catch (e) {
                 // Ignore
              }
          } else {
             cleanText = cleanText.replace(
                /(?<!```json\n)(?:^|\n)(\{[\s\S]*?\})(?=\n|$)/g,
                (match: string, jsonPart: string) => {
                  try {
                    const parsed = JSON.parse(jsonPart);
                    return (
                      "\n```json\n" + JSON.stringify(parsed, null, 2) + "\n```\n"
                    );
                  } catch (e) {
                    return match;
                  }
                },
              );
          }
        }

        let displayLabel = "MESSAGE";
        const evt = msg.event || "";
        if (isA2UI || evt === "a2ui") {
          displayLabel = "A2UI_SURFACE";
        } else if (evt === "json") {
          displayLabel = "JSON";
        } else if (evt === "tool_start") {
          displayLabel = "TOOL START";
          if (pulse && typeof pulse === "object" && pulse.tool) {
            const toolName = pulse.tool.toUpperCase().replace(/_/g, " ");
            const hints = pulse.tool_hints;
            if (hints && typeof hints === "object") {
              const hintValues = Object.values(hints).join(", ");
              displayLabel = `TOOL START: ${toolName} [${hintValues}]`;
            } else {
              displayLabel = `TOOL START: ${toolName}`;
            }
          }
        } else if (evt === "tool_end") {
          displayLabel = "TOOL END";
          if (pulse && typeof pulse === "object" && pulse.tool_name) {
             displayLabel = `TOOL END: ${pulse.tool_name.toUpperCase()}`;
          }
        } else if (evt === "model_end") {
          displayLabel = "MODEL END";
        } else if (evt === "model_error" || evt === "tool_error") {
          displayLabel = "ERROR";
        } else if (evt === "text" || evt === "narrative") {
          displayLabel = "TEXT";
        } else {
          displayLabel = evt.toUpperCase().replace(/_/g, " ");
        }

        const messageEl = renderA2UI(
          {
            id: `mb_${Math.random().toString(36).substring(7)}`,
            component: {
              MessageBox: {
                speaker: speaker,
                text: cleanText,
                typeLabel: displayLabel,
                children: a2uiElements,
                rawMessage: msg,
                sessionId: targetSessionId,
                simulationId: msg.simulationId || undefined,
              },
            },
          },
          { components: {}, color: sessionColor },
        );

        const container = logsContainer();
        if (container && messageEl) {
          messageEl.classList.add(
            "max-w-full",
            "break-words",
            "min-w-0",
            "shrink-0"
          );
          logBuffer.append(messageEl);
        }
      } else if (msg.event === "crowd_reaction") {
        const reactionData = msg.data;
        let summary = "";
        if (reactionData?.aggregate) {
          const counts = reactionData.aggregate.counts || {};
          const total = reactionData.aggregate.total || 0;
          const emojis = Object.entries(counts)
            .map(([emoji, count]) => `${emoji} ×${count}`)
            .join("  ");
          summary = `🎭 Crowd Reaction (${total} total): ${emojis}`;
        } else if (reactionData?.details) {
          const emojis = reactionData.details
            .map((r: any) => r.emoji || r.type)
            .join(" ");
          summary = `🎭 Crowd Reaction: ${emojis}`;
        } else {
          summary = `🎭 Crowd Reaction: ${JSON.stringify(reactionData)}`;
        }
        log(summary, "recv", {
          originId: "collector",
          originType: "telemetry",
          rawMessage: Object.assign({}, wrapper, { payload: reactionData }),
        });
      } else if (msg.event === "environment_reset") {
        log("Environment reset detected — clearing local state", "info");
        activeSessions.clear();
        renderSessionList();
      } else if (msg.event !== "broadcast") {
        const targetSessionId =
          msg.origin.sessionId || msg.origin.session_id || "unknown";
        log(`Event: ${msg.event}`, "recv", {
          originId: targetSessionId,
          rawMessage: Object.assign({}, wrapper, { payload: data }),
        });
      }
    } catch (e) {
      log(`Failed to process message: ${e}`, "err");
    }
  };

  ws.onclose = () => {
    log("Monitor disconnected — reconnecting in 2s", "err");
    monitorSocket = null;
    setTimeout(connectMonitor, 2000);
  };

  ws.onerror = () => {
    log("Monitor connection error", "err");
  };
}

// --- Agent Management ---
async function spawnAgent(type: string, count: number = 1): Promise<string[]> {
  try {
    log(`Spawning ${count}× ${type} via batch API`, "info");

    const baseUrl = wsToHttp(gatewayInput().value);

    const resp = await fetch(`${baseUrl}/api/v1/spawn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agents: [{ agentType: type, count }] }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      log(`Spawn failed: ${err.error}`, "err");
      return [];
    }

    const result = await resp.json();
    const sessions: string[] = [];

    for (const s of result.sessions || []) {
      activeSessions.set(s.sessionId, { agentType: s.agentType });
      sessions.push(s.sessionId);
      log(
        `${s.agentType} session ${s.sessionId.substring(0, 8)}… spawned`,
        "info",
        {
          originId: s.sessionId,
        },
      );
    }

    renderSessionList();
    return sessions;
  } catch (e) {
    log(`Spawn failed: ${e}`, "err");
    return [];
  }
}
function renderSessionList() {
  const countSpan = document.getElementById("session-count");
  if (countSpan) {
    countSpan.innerText = activeSessions.size.toString();
  }
  const list = sessionList();
  if (!list) return;

  const search = sessionSearchInput()?.value.toLowerCase();
  const sessions = Array.from(activeSessions.entries()).filter(
    ([sid, s]) =>
      !search ||
      sid.toLowerCase().includes(search) ||
      s.agentType.toLowerCase().includes(search),
  );

  if (sessions.length === 0) {
    list.innerHTML =
      '<p class="text-sm text-slate-600 italic text-center py-8 px-4">No sessions match the filter.</p>';
    return;
  }

  list.innerHTML = sessions
    .map(
      ([sid, session]) => `
    <div class="dense-list-item flex items-center gap-3">
      <input type="checkbox" data-sid="${sid}" class="rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500/20 w-3.5 h-3.5" checked />
      <div class="flex-1 min-w-0">
        <div class="text-[10px] font-bold text-slate-200 truncate font-mono">${sid}</div>
        <div class="text-[8px] text-slate-500 uppercase font-bold tracking-widest">${session.agentType}</div>
      </div>
      <div class="dot-live scale-75"></div>
    </div>
  `,
    )
    .join("");
}

function sendTargetedBroadcast(
  manualPayload?: string,
  manualTargets?: string[],
) {
  const payload = manualPayload || broadcastPayload().value;
  const targets =
    manualTargets ||
    Array.from(
      document.querySelectorAll('input[type="checkbox"][data-sid]:checked'),
    ).map((el) => (el as HTMLInputElement).dataset.sid!);

  if (targets.length === 0) {
    log("No target NPCs selected", "err");
    return;
  }

  if (!monitorSocket || monitorSocket.readyState !== WebSocket.OPEN) {
    log("Monitor socket not connected", "err");
    return;
  }

  try {
    let jsonPayload: any;
    try {
      jsonPayload = JSON.parse(payload || "{}");
    } catch {
      jsonPayload = { text: payload };
    }

    const innerPayload = new TextEncoder().encode(JSON.stringify(jsonPayload));

    const brMsg = {
      payload: innerPayload,
      targetSessionIds: targets,
    };
    const brBinary = BroadcastRequest.encode(
      BroadcastRequest.create(brMsg),
    ).finish();

    const msg = {
      origin: { type: "client", id: "tester-ui", sessionId: "tester-ui" },
      destination: targets,
      status: "success",
      type: "broadcast",
      event: "broadcast",
      payload: brBinary,
    };

    const binary = Wrapper.encode(Wrapper.create(msg)).finish();
    monitorSocket.send(binary);

    log(
      `Emitted pulse to ${targets.length} units:\n${JSON.stringify(jsonPayload, null, 2)}`,
      "send",
      { destination: targets, rawMessage: msg },
    );
    if (!manualPayload) {
      broadcastPayload().value = "";
    }
  } catch (e) {
    log(`Broadcast failed: ${e}`, "err");
  }
}

function sendA2UIAction(sessionId: string, actionName: string) {
  if (!monitorSocket || monitorSocket.readyState !== WebSocket.OPEN) {
    log("Monitor socket not connected", "err");
    return;
  }

  try {
    const action = {
      sessionId: sessionId,
      actionName: actionName,
    };
    const actionBinary = A2UIAction.encode(A2UIAction.create(action)).finish();

    const msg = {
      origin: { type: "client", id: "tester-ui", sessionId: "tester-ui" },
      destination: [sessionId],
      status: "success",
      type: "a2ui_action",
      event: "a2ui_action",
      payload: actionBinary,
      requestId: crypto.randomUUID(),
    };

    const binary = Wrapper.encode(Wrapper.create(msg)).finish();
    monitorSocket.send(binary);

    log(
      `A2UI Action: "${actionName}" -> session ${sessionId.substring(0, 8)}...`,
      "send",
    );
  } catch (e) {
    log(`A2UI Action failed: ${e}`, "err");
  }
}

// Global Event Listeners
app.addEventListener("click", (e) => {
  const target = e.target as HTMLElement;
  const spawnBtn = target.closest<HTMLButtonElement>(".spawn-btn");
  if (spawnBtn) {
    const type = spawnBtn.dataset.type!;
    const countInput =
      spawnBtn.parentElement?.querySelector<HTMLInputElement>(
        ".spawn-count-input",
      );
    const count = parseInt(countInput?.value || "1");
    spawnAgent(type, count);
  }
});

function getGatewayUrl(): string {
  const env = (window as any).ENV || {};
  const configured = env.VITE_GATEWAY_URL || "/ws";
  // Relative path: construct full URL from current page
  if (configured.startsWith("/")) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}${configured}`;
  }
  return configured;
}

async function start() {
  app.innerHTML = `
    <div class="flex h-screen bg-slate-950 text-slate-200 font-sans overflow-hidden">
        <!-- Sidebar: Configuration & Catalog -->
        <div class="w-80 border-r border-slate-800 bg-slate-900/50 flex flex-col">
            <div class="p-6 border-b border-slate-800 flex flex-col gap-4">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                        <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                    </div>
                    <div>
                        <h1 class="text-xs font-black tracking-tighter text-white uppercase italic">Tester</h1>
                        <p class="text-[8px] font-bold text-slate-500 tracking-widest uppercase">Expert Control Node</p>
                    </div>
                </div>
                
                <div class="flex flex-col gap-1.5">
                    <label class="text-[9px] font-black text-slate-500 uppercase tracking-widest">Gateway Link</label>
                    <input id="gateway-url" type="text" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-mono text-indigo-400 focus:border-indigo-500 outline-none transition-colors" value="" />
                </div>
            </div>

            <div class="flex-1 overflow-y-auto custom-scrollbar p-6 flex flex-col gap-8">
                <!-- NPC Catalog -->
                <div class="flex flex-col gap-4">
                    <div class="flex items-center justify-between">
                        <h2 class="text-[10px] font-black text-white uppercase tracking-widest">NPC Catalog</h2>
                        <button id="refresh-agents" class="p-1 px-2 rounded-md bg-slate-800 text-[8px] font-bold text-slate-400 hover:bg-slate-700 transition-all uppercase">Refresh</button>
                    </div>
                    <div id="agent-catalog-list" class="flex flex-col gap-2">
                        <!-- catalog items injected here -->
                    </div>
                </div>

                <!-- Active Sessions -->
                <div class="flex flex-col gap-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <h2 class="text-[10px] font-black text-white uppercase tracking-widest">Active Links</h2>
                            <span id="session-count" class="px-1.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-[9px] font-black text-indigo-400 italic">0</span>
                        </div>
                        <div class="flex gap-1.5">
                            <button id="select-all" class="text-[8px] font-bold text-slate-500 hover:text-indigo-400 uppercase">All</button>
                            <button id="deselect-all" class="text-[8px] font-bold text-slate-500 hover:text-indigo-400 uppercase">None</button>
                        </div>
                    </div>
                    <div class="relative">
                        <input id="session-search" type="text" class="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-8 py-1.5 text-[10px] outline-none focus:border-indigo-500/30 transition-all" placeholder="Filter IDs..." />
                        <svg class="w-3 h-3 absolute left-2.5 top-2 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                    </div>
                    <div id="session-list" class="flex flex-col gap-1.5 max-h-[200px] overflow-y-auto custom-scrollbar">
                        <!-- session list items injected here -->
                    </div>
                    <button id="stop-selected" class="w-full py-2 border border-red-500/30 text-red-500/60 text-[9px] font-bold rounded-lg hover:bg-red-500/10 transition-all uppercase tracking-widest">Terminate Selected</button>
                </div>
            </div>

            <div class="p-4 border-t border-slate-800 space-y-3">
                <div class="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Environment Reset</div>
                <div class="flex flex-col gap-1.5">
                    <label class="flex items-center gap-2 text-[10px] text-slate-400 cursor-pointer">
                        <input type="checkbox" id="reset-sessions" checked class="accent-red-500 w-3 h-3" />
                        Sessions
                    </label>
                    <label class="flex items-center gap-2 text-[10px] text-slate-400 cursor-pointer">
                        <input type="checkbox" id="reset-queues" checked class="accent-red-500 w-3 h-3" />
                        Spawn Queues
                    </label>
                    <label class="flex items-center gap-2 text-[10px] text-slate-400 cursor-pointer">
                        <input type="checkbox" id="reset-maps" checked class="accent-red-500 w-3 h-3" />
                        Session Maps
                    </label>
                </div>
                <button id="flush-sessions" class="w-full py-2 text-slate-600 text-[9px] font-black hover:text-red-400 transition-all uppercase tracking-widest">Reset Environment</button>
            </div>
        </div>

        <!-- Main Workspace -->
        <div class="flex-1 flex flex-col bg-slate-950 relative min-w-0 min-h-0">
            <div class="h-16 px-8 border-b border-slate-800 flex items-center justify-between bg-slate-900/20 backdrop-blur-md sticky top-0 z-40">
                <div class="flex items-center gap-6 min-w-0">
                    <h2 id="view-title" class="text-xs font-black text-white uppercase tracking-[0.2em] italic truncate pr-4">Simulation Pulse</h2>
                    <div id="log-controls" class="flex items-center gap-4">
                        <div class="relative">
                            <input id="log-filter" type="text" class="w-48 bg-slate-900/40 border border-slate-800 rounded-full px-8 py-1 text-[10px] outline-none focus:border-indigo-500/30 transition-all" placeholder="Filter logs..." />
                            <svg class="w-3 h-3 absolute left-3 top-1.5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/></svg>
                        </div>
                        <button id="clear-logs" class="text-[9px] font-bold text-slate-500 hover:text-white transition-all uppercase">Clear History</button>
                        <span id="dropped-count" class="text-[9px] font-bold text-amber-500/70 uppercase hidden">Dropped: <span id="dropped-value">0</span></span>
                    </div>
                </div>
                
            </div>

            <div id="view-container" class="flex-1 overflow-x-hidden relative flex flex-col min-w-0 min-h-0">
                <div id="logs" class="flex-1 overflow-y-auto overflow-x-hidden p-12 flex flex-col gap-6 custom-scrollbar w-full box-border min-h-0">
                    <!-- log pulses injected here -->
                </div>
                <button id="scroll-to-bottom" class="hidden absolute bottom-4 right-8 z-30 p-2.5 rounded-full bg-indigo-600 text-white shadow-lg shadow-indigo-500/30 hover:bg-indigo-500 active:scale-95 transition-all" title="Scroll to bottom">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 14l-7 7m0 0l-7-7m7 7V3"/></svg>
                </button>
            </div>

            <!-- Global Input Footer -->
            <div class="p-6 border-t border-slate-800 bg-slate-900/40 backdrop-blur-md">
                <div class="max-w-4xl mx-auto flex gap-4">
                    <div class="flex-1 relative">
                        <textarea id="broadcast-payload" rows="1" class="w-full bg-slate-950 border border-slate-800 rounded-2xl px-6 py-4 text-xs font-medium focus:border-indigo-500 outline-none transition-all custom-scrollbar resize-none" placeholder="Broadcast intent to all active agents... (Cmd+Enter to emit)"></textarea>
                    </div>
                    <button id="broadcast-btn" class="px-8 bg-indigo-600 text-white text-[10px] font-black rounded-2xl hover:bg-indigo-500 active:scale-[0.98] transition-all shadow-lg shadow-indigo-500/20 uppercase tracking-widest">Emit Pulse</button>
                </div>
            </div>
        </div>
    </div>
  `;

  // Set gateway URL from BFF config.js (window.ENV)
  gatewayInput().value = getGatewayUrl();

  await initProto();

  // Initialize logBuffer BEFORE connectMonitor() -- connectMonitor() calls
  // log() synchronously which requires logBuffer to exist.
  const droppedEl = document.getElementById("dropped-value");
  const droppedContainer = document.getElementById("dropped-count");
  logBuffer = createLogBuffer({
    container: logsContainer,
    onEvict: (total) => {
      if (droppedEl) droppedEl.textContent = total.toLocaleString();
      if (droppedContainer) droppedContainer.classList.remove("hidden");
    },
    onScroll: maybeAutoScroll,
  });

  connectMonitor();
  await refreshCatalog();

  document
    .getElementById("refresh-agents")
    ?.addEventListener("click", refreshCatalog);
  document
    .getElementById("broadcast-btn")
    ?.addEventListener("click", () => sendTargetedBroadcast());

  broadcastPayload()?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendTargetedBroadcast();
    }
  });

  document.getElementById("clear-logs")?.addEventListener("click", () => {
    const container = logsContainer();
    if (container) container.innerHTML = "";
    logBuffer.reset();
    const dc = document.getElementById("dropped-count");
    if (dc) dc.classList.add("hidden");
  });

  sessionSearchInput()?.addEventListener("input", renderSessionList);

  document.getElementById("select-all")?.addEventListener("click", () => {
    document
      .querySelectorAll('#session-list input[type="checkbox"]')
      .forEach((el) => ((el as HTMLInputElement).checked = true));
  });
  document.getElementById("deselect-all")?.addEventListener("click", () => {
    document
      .querySelectorAll('#session-list input[type="checkbox"]')
      .forEach((el) => ((el as HTMLInputElement).checked = false));
  });

  document.getElementById("stop-selected")?.addEventListener("click", () => {
    const targets = Array.from(
      document.querySelectorAll('#session-list input[type="checkbox"]:checked'),
    ).map((el) => (el as HTMLInputElement).dataset.sid!);
    targets.forEach((sid) => {
      activeSessions.delete(sid);
    });
    renderSessionList();
    log(`Removed ${targets.length} sessions from tracking`, "info");
  });

  const logsEl = document.getElementById("logs") as HTMLDivElement;

  // --- Smart auto-scroll ---
  const scrollBtn = document.getElementById("scroll-to-bottom")!;

  logsEl.addEventListener("scroll", () => {
    userIsNearBottom = isNearBottom(logsEl);
    if (userIsNearBottom) {
      scrollBtn.classList.add("hidden");
    } else {
      scrollBtn.classList.remove("hidden");
    }
  });

  scrollBtn.addEventListener("click", () => {
    logsEl.scrollTop = logsEl.scrollHeight;
    userIsNearBottom = true;
    scrollBtn.classList.add("hidden");
  });

  document
    .getElementById("flush-sessions")
    ?.addEventListener("click", async () => {
      try {
        const baseUrl = wsToHttp(gatewayInput().value);
        const targets: string[] = [];
        if ((document.getElementById("reset-sessions") as HTMLInputElement)?.checked) targets.push("sessions");
        if ((document.getElementById("reset-queues") as HTMLInputElement)?.checked) targets.push("queues");
        if ((document.getElementById("reset-maps") as HTMLInputElement)?.checked) targets.push("maps");

        if (targets.length === 0) {
          log("No reset targets selected", "err");
          return;
        }

        const body = targets.length < 3 ? JSON.stringify({ targets }) : undefined;
        const resp = await fetch(`${baseUrl}/api/v1/environment/reset`, {
          method: "POST",
          headers: body ? { "Content-Type": "application/json" } : {},
          body,
        });
        const data = await resp.json();
        if (!resp.ok) {
          log(`Reset failed: ${data.error ?? resp.statusText}`, "err");
          return;
        }
        const results = data.results;
        const parts: string[] = [];
        if (results.sessions?.flushed) parts.push(`${results.sessions.count} session(s)`);
        if (results.queues?.flushed) parts.push(`${results.queues.count} queue(s)`);
        if (results.maps?.flushed) parts.push(`${results.maps.count} map(s)`);
        log(`Environment reset: ${parts.join(", ")}`, "info");
        if (results.sessions?.flushed) {
          activeSessions.clear();
          renderSessionList();
        }
      } catch (e) {
        log(`Reset failed: ${e}`, "err");
      }
    });
}

start();
