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

export interface Skill {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

export interface AgentCard {
  name: string;
  description: string;
  version: string;
  url: string;
  preferred_transport: string;
  skills: Skill[];
}

export interface AgentCatalog {
  [key: string]: AgentCard;
}

export async function fetchAgentTypes(
  gatewayUrl: string,
): Promise<AgentCatalog> {
  // Robustly resolve base URL
  let baseUrl = gatewayUrl;
  if (gatewayUrl.startsWith("/")) {
    baseUrl = window.location.origin + gatewayUrl;
  }

  // Convert ws:// or wss:// to http:// or https:// for the API
  baseUrl = baseUrl
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

  const response = await fetch(`${baseUrl}/api/v1/agent-types`);
  if (!response.ok) {
    throw new Error(`Failed to fetch agent types: ${response.statusText}`);
  }
  return response.json();
}

export async function createAgentSession(
  agentUrl: string,
  userId: string = "tester-ui",
): Promise<string> {
  // ADK create_session call
  const response = await fetch(`${agentUrl}/create_session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_id: userId,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to create agent session: ${response.statusText}`);
  }

  const data = await response.json();
  return data.id || data.session_id;
}

export async function createOrchestratedSession(
  gatewayUrl: string,
  agentType: string,
  userId: string = "tester-ui",
): Promise<string> {
  // Robustly resolve base URL
  let baseUrl = gatewayUrl;
  if (gatewayUrl.startsWith("/")) {
    baseUrl = window.location.origin + gatewayUrl;
  }

  // Convert ws:// or wss:// to http:// or https:// for the API
  baseUrl = baseUrl
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

  const response = await fetch(`${baseUrl}/api/v1/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      agentType,
      userId,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to trigger orchestration: ${response.statusText}`);
  }

  const data = await response.json();
  return data.sessionId;
}
