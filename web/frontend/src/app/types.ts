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

// 1. Define the object with 'as const' to keep the values literal
export const AgentMessageType = {
  RUN_START: 'run_start',
  RUN_END: 'run_end',
  AGENT_START: 'agent_start',
  AGENT_END: 'agent_end',
  MODEL_START: 'model_start',
  MODEL_END: 'model_end',
  MODEL_ERROR: 'model_error',
  TOOL_START: 'tool_start',
  TOOL_END: 'tool_end',
  TOOL_ERROR: 'tool_error',
  TEXT: 'text',
  SYSTEM: 'system',
  INTER_AGENT: 'inter_agent',
  TICK: 'tick',
} as const;

export const AgentToolName = {
  ADD_MEDICAL_TENTS: 'add_medical_tents',
};

// 2. Derive the type from the object
export type AgentMessageType = (typeof AgentMessageType)[keyof typeof AgentMessageType];

export type ChatAgent = 'planner' | 'planner_with_eval' | 'simulator' | 'simulator_with_failure';
