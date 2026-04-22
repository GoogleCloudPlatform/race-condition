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
 * Thin Angular adapter over AgentGateway.
 * Only responsibility: bridge the framework-agnostic callbacks into
 * NgZone-aware RxJS Subjects so Angular's change detection fires correctly.
 */

import { Injectable, NgZone, OnDestroy } from '@angular/core';
import { Subject } from 'rxjs';
import { agentGateway, BackendAgent, ChatMessage } from './agent-gateway-updates';

export type { BackendAgent, ChatMessage };

@Injectable({ providedIn: 'root' })
export class GatewayService implements OnDestroy {
  readonly agents$ = new Subject<BackendAgent[]>();
  readonly chat$ = new Subject<ChatMessage>();

  private unsubSessions: () => void;
  private unsubChat: () => void;

  constructor(private ngZone: NgZone) {
    this.unsubSessions = agentGateway.onSessionsChange((sessions) =>
      this.ngZone.run(() => this.agents$.next(sessions)),
    );
    this.unsubChat = agentGateway.onChat((msg) => this.ngZone.run(() => this.chat$.next(msg)));
  }

  ngOnDestroy(): void {
    this.unsubSessions();
    this.unsubChat();
  }

  addAgent(agentType = 'runner_autopilot'): Promise<string> {
    return agentGateway.addAgent(agentType);
  }

  removeAgent(guid: string): void {
    agentGateway.removeAgent(guid);
  }

  sendBroadcast(text: string, targetGuids: string[], silent = false, isOrganizer = false): void {
    agentGateway.sendBroadcast(text, targetGuids, silent, isOrganizer);
  }

  getAgents(): BackendAgent[] {
    return agentGateway.getSessions();
  }

  hasAgent(guid: string): boolean {
    return agentGateway.hasSession(guid);
  }

  getOrganizerGuid(): string {
    return agentGateway.getOrganizerGuid();
  }

  removeCurrentSimulationId(): void {
    agentGateway.removeCurrentSimulationId();
  }

  resetDemoChatPipelineState(): void {
    agentGateway.resetDemoChatPipelineState();
  }

  setFilterSettings(settings: Partial<{ showLoadSkills: boolean }>): void {
    agentGateway.setFilterSettings(settings);
  }
}
