/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Injectable, inject, ChangeDetectorRef } from '@angular/core';
import { GatewayService, type BackendAgent } from '../../../../../gateway.service';

@Injectable()
export class AgentGatewayAgentsService {
  private readonly gateway = inject(GatewayService);
  private cdr!: ChangeDetectorRef;

  agents: Record<string, string | null> = {};
  initializingAgents: Record<string, boolean> = {};

  connect(cdr: ChangeDetectorRef): void {
    this.cdr = cdr;
  }

  private mark(): void {
    this.cdr.markForCheck();
  }

  getAgentDisplayName(agentType: string): string {
    const sessions = this.gateway.getAgents();
    const session = sessions.find((s: BackendAgent) => s.agentType === agentType);
    if (session?.displayName) return session.displayName;
    return agentType;
  }

  onRemoveAgent(agentType: string): void {
    const guid = this.agents[agentType];
    if (guid) this.gateway.removeAgent(guid);
    this.agents[agentType] = null;
    this.mark();
  }

  removeAllActiveAgents(): void {
    Object.entries(this.agents).forEach(([agentType, guid]) => {
      if (guid) this.gateway.removeAgent(guid);
      this.agents[agentType] = null;
    });
    this.initializingAgents = {};
    this.mark();
  }

  async onInitAgent(agentType: string, runCachedMessages: boolean): Promise<void> {
    if (runCachedMessages) return;
    if (this.agents[agentType] || this.initializingAgents[agentType]) return;
    this.initializingAgents[agentType] = true;
    this.mark();
    try {
      this.agents[agentType] = await this.gateway.addAgent(agentType);
      this.mark();
    } catch (e) {
      console.error(`Init Agent ${agentType} failed:`, e);
    } finally {
      this.initializingAgents[agentType] = false;
      this.mark();
    }
  }
}
