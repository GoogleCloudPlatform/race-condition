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
 * Typed message API for gateway payloads.
 *
 * The new backend sends messages as `{ text: string; emotion?: string }` JSON
 * payloads inside the protobuf Wrapper. This module parses those payloads into
 * a discriminated union of typed messages with good editor intellisense.
 *
 * Message lifecycle for a typical agent run:
 *   FunctionCallMessage → ToolResultMessage → ... → ModelTextMessage → (NarrativeMessage duplicate)
 */

// ── Parsed content types ──────────────────────────────────────────────────────

/** A single function call extracted from a model output. */
export interface ParsedFunctionCall {
  readonly name: string;
  readonly argsRaw: string; // raw Python repr of the args dict (for display)
}

/** A tool/function execution result parsed from JSON. */
export interface ToolResult {
  readonly status: 'success' | 'error';
  readonly message: string;
  readonly errorCode?: string;
  readonly skillName?: string;
  readonly geojson?: any;
  readonly data: Record<string, unknown>;
}

// ── Discriminated union ───────────────────────────────────────────────────────

/** The model decided to call one or more tools/functions. */
export interface FunctionCallMessage {
  readonly kind: 'function_call';
  readonly agent: string; // e.g. "Planner"
  readonly calls: ParsedFunctionCall[];
  readonly emotion: string;
}

/** A tool returned a result (success or error). */
export interface ToolResultMessage {
  readonly kind: 'tool_result';
  readonly result: ToolResult;
  readonly emotion: string;
}

/** The model produced a final readable text response. */
export interface ModelTextMessage {
  readonly kind: 'model_text';
  readonly agent: string;
  readonly text: string;
  readonly emotion: string;
}

/** A tool execution error reported by the agent. */
export interface ToolErrorMessage {
  readonly kind: 'tool_error';
  readonly agent: string;
  readonly toolName: string;
  readonly errorText: string;
  readonly emotion: string;
}

/** Plain narrative text (often a duplicate of ModelTextMessage). */
export interface NarrativeMessage {
  readonly kind: 'narrative';
  readonly text: string;
  readonly emotion: string;
}

/** All possible parsed message types. */
export type GatewayMessage =
  | FunctionCallMessage
  | ToolResultMessage
  | ToolErrorMessage
  | ModelTextMessage
  | NarrativeMessage
  | {
      readonly kind: 'model_end';
      readonly text: string;
      readonly emotion: string;
    };

// ── Parser ────────────────────────────────────────────────────────────────────

const MODEL_END_PREFIX = /^\[(\w+)\] Model End\n\n([\s\S]*)$/;
const TOOL_ERROR_PREFIX = /^\[(\w+)\] Tool Error:\s*(\S+)\n([\s\S]*)$/;

/**
 * Parse a raw gateway payload into a typed message.
 * Returns `null` for messages that should be silently skipped (e.g. metadata-only model outputs).
 */
export function parseGatewayPayload(data: {
  text?: string;
  emotion?: string;
  a2ui?: any;
  result?: { status?: string; a2ui?: string; [key: string]: any };
  [key: string]: any;
}): GatewayMessage | null {
  const text = data.text ?? '';
  const emotion = data.emotion ?? '';

  if (data.a2ui) {
    return {
      kind: 'tool_result',
      emotion,
      result: {
        data,
        status: 'success',
        message: 'a2ui',
      },
    };
  }

  if (data.result?.a2ui) {
    let parsedA2ui: any;
    try {
      parsedA2ui =
        typeof data.result.a2ui === 'string' ? JSON.parse(data.result.a2ui) : data.result.a2ui;
    } catch (e) {
      console.error('Failed to parse a2ui:', e);
      parsedA2ui = data.result.a2ui;
    }

    return {
      kind: 'tool_result',
      emotion,
      result: {
        data: { ...data, a2ui: parsedA2ui },
        status: (data.result.status as 'success' | 'error') || 'success',
        message: 'a2ui',
      },
    };
  }

  if (!text) return null;

  // ── [Agent] Tool Error ────────────────────────────────────────────────
  const errorMatch = text.match(TOOL_ERROR_PREFIX);
  if (errorMatch) {
    return {
      kind: 'tool_error',
      agent: errorMatch[1],
      toolName: errorMatch[2],
      errorText: errorMatch[3].trim(),
      emotion,
    };
  }

  // ── [Agent] Model End ───────────────────────────────────────────────────
  const prefixMatch = text.match(MODEL_END_PREFIX);
  if (prefixMatch) {
    const agent = prefixMatch[1];
    const content = prefixMatch[2];

    // Extract function calls from Python repr output
    const calls = extractFunctionCalls(content);
    if (calls.length > 0) {
      return { kind: 'function_call', agent, calls, emotion };
    }

    // If content starts with media_resolution= it's metadata-only (no function call, no text) → skip
    if (content.startsWith('media_resolution=')) {
      return null;
    }

    // Readable text from the model
    const trimmed = content.trim();
    if (trimmed) {
      return { kind: 'model_text', agent, text: trimmed, emotion };
    }

    return null;
  }

  // ── JSON tool result ────────────────────────────────────────────────────
  const trimmed = text.trim();
  if (trimmed.startsWith('{')) {
    try {
      const json = JSON.parse(trimmed);
      if (typeof json === 'object' && json !== null) {
        return {
          kind: 'tool_result',
          emotion,
          result: {
            status: json.error ? 'error' : json.status || 'success',
            message: json.error || json.message || '',
            errorCode: json.error_code,
            skillName: json.skill_name,
            geojson: json.geojson,
            data: json,
          },
        };
      }
    } catch {
      /* not valid JSON, fall through */
    }
  }
  // ── Plain text / narrative ──────────────────────────────────────────────
  return { kind: 'narrative', text, emotion };
}

/**
 * Extract all FunctionCall instances from a model output's Python repr.
 *
 * Handles formats like:
 *   function_call=FunctionCall(args={...}, name='tool_name')
 *   function_call=FunctionCall(name='tool_name', args={...})
 */
function extractFunctionCalls(content: string): ParsedFunctionCall[] {
  const calls: ParsedFunctionCall[] = [];

  // Split on function_call=FunctionCall( to find each call
  const chunks = content.split('function_call=FunctionCall(');
  for (let i = 1; i < chunks.length; i++) {
    const chunk = chunks[i];

    // Extract the function name
    const nameMatch = chunk.match(/name='([^']+)'/);
    if (!nameMatch) continue;

    // Extract args — find the args={...} block
    let argsRaw = '{}';
    const argsMatch = chunk.match(/args=(\{[\s\S]*?\})\s*[,)]/);
    if (argsMatch) {
      argsRaw = argsMatch[1];
    }

    calls.push({ name: nameMatch[1], argsRaw });
  }

  return calls;
}

// ── Utility ───────────────────────────────────────────────────────────────────

/** Icon for a given tool name (used by gateway and HUD). */
export function toolIcon(tool: string): string {
  switch (tool) {
    case 'get_vitals':
      return 'monitor_heart';
    case 'accelerate':
      return 'speed';
    case 'load_skill':
      return 'extension';
    case 'plan_marathon_route':
      return 'route';
    case 'plan_marathon_event':
      return 'event';
    case 'add_water_stations':
      return 'water_drop';
    case 'add_medical_tents':
      return 'local_hospital';
    case 'report_marathon_route':
      return 'flag';
    case 'start_race':
      return 'directions_run';
    case 'relay_to_runner':
      return 'transfer_within_a_station';
    case 'prepare_simulation':
      return 'settings';
    case 'spawn_runners':
      return 'group_add';
    case 'start_race_collector':
      return 'sensors';
    case 'fire_start_gun':
      return 'campaign';
    case 'advance_tick':
      return 'update';
    case 'check_race_complete':
      return 'flag';
    case 'compile_results':
      return 'assessment';
    case 'stop_race_collector':
      return 'sensors_off';
    case 'verify_plan':
      return 'verified';
    case 'call_agent':
      return 'swap_horiz';
    default:
      return 'build';
  }
}

/** Check if a tool result carries GeoJSON data. */
export function hasGeoData(toolName: string | undefined, result: ToolResult): boolean {
  return !!(
    result.geojson ||
    toolName === 'add_medical_tents' ||
    toolName === 'add_water_stations' ||
    toolName === 'plan_marathon_route' ||
    toolName === 'report_marathon_route'
  );
}
