/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import type { ChangeDetectorRef, ElementRef } from '@angular/core';
import { Injectable } from '@angular/core';
import type { ChatMessage } from '../../../../../gateway.service';
import { agentGateway } from '../../../../../agent-gateway-updates';
import { DEMO_CONFIG } from '../../../../../demo-config';
import { AgentMessageType } from '../../../../../types';
import { demoFiveSpeaker } from '../../../../../../constants';
import type { DemoService } from '../../../../DemoOverlay/demo.service';
import type { DisplayItem } from '../agent-screen.types';

/** Structural subset of AgentScreen passed into display processing (avoids circular imports). */
export interface AgentChatDisplayHost {
  cdr: ChangeDetectorRef;
  agents: Record<string, string | null>;
  currentAgent: { agentType: string; sessionId: string } | null;
  chatMessages: ChatMessage[];
  chatInput: string;
  chatTextAreaRef?: ElementRef<HTMLTextAreaElement>;
  demoService: DemoService;
  filterSettings: { showToolCalls: boolean; showLoadSkills: boolean };
  isSecuringAgent: boolean;
  isAgentWorking: boolean;
  finalToolCallMessage: DisplayItem | null;
  errorMessageInterval: number | null;
  resetSimulationStatistics(): void;
  handleRaceStarted(): void;
  handleTickUpdate(d: Record<string, unknown>): void;
  scrollChatToBottom(): void;
  autoResize(): void;
}

@Injectable()
export class AgentChatDisplayService {
  displayItems: DisplayItem[] = [];
  expandedToolCalls = new Set<number>();
  activeToolCalls = new Map<string, number>();

  clearForDemoReset(): void {
    this.displayItems = [];
    this.expandedToolCalls.clear();
    this.activeToolCalls.clear();
  }

  toggleToolCall(idx: number): void {
    if (this.expandedToolCalls.has(idx)) {
      this.expandedToolCalls.delete(idx);
    } else {
      this.expandedToolCalls.add(idx);
    }
  }

  displayText(m: ChatMessage): string {
    if (m.msgType === 'tool_end' && m.text) {
      try {
        const parsed = JSON.parse(m.text) as {
          result?: { message?: string };
          message?: string;
        };
        return parsed?.result?.message || parsed?.message || m.toolName || 'Done';
      } catch {
        /* fall through */
      }
    }
    return m.text;
  }

  trackByDisplayItem(i: number, item: DisplayItem): string {
    if (item.kind === 'tick_progress') {
      return `tick:${item.guid}:${item.tick}`;
    }
    if ('msg' in item && item.msg) {
      const m = item.msg;
      const ts = m.timestamp instanceof Date ? m.timestamp.getTime() : 0;
      return `${item.kind}:${m.guid ?? ''}:${m.msgType ?? ''}:${m.toolName ?? ''}:${ts}:${i}`;
    }
    if (item.kind === 'a2ui') {
      return `a2ui:${i}`;
    }
    return `${(item as DisplayItem).kind}:${i}`;
  }

  setToolCallToWarning(host: AgentChatDisplayHost): void {
    const toolCallToWarn = this.displayItems.find((item) => {
      if (!('msg' in item)) return false;
      return (
        item.msg.speaker.includes('simulation_pipeline') &&
        item.msg.toolName === 'prepare_simulation'
      );
    });
    if (!toolCallToWarn || toolCallToWarn.kind !== 'tool_call') return;

    toolCallToWarn.done = true;
    toolCallToWarn.warning = true;
    toolCallToWarn.msg = { ...toolCallToWarn.msg, text: this.displayText(toolCallToWarn.msg) };

    this.displayItems = [...this.displayItems];
    host.cdr.markForCheck();
  }

  addDisplayItem(host: AgentChatDisplayHost, item: DisplayItem): void {
    if (host.isSecuringAgent) return;
    this.displayItems = [...this.displayItems, item];
    host.cdr.markForCheck();
  }

  finishToolCall(host: AgentChatDisplayHost, msg: ChatMessage): void {
    if (!msg.toolName) return;
    const idx = this.activeToolCalls.get(
      msg.toolName === 'load_skill' ? msg.skillName! : msg.toolName,
    );

    if (idx === undefined) return;

    const item = this.displayItems[idx];
    if (!item || item.kind !== 'tool_call') return;

    item.done = true;
    item.msg = { ...item.msg, text: this.displayText(msg) };
    this.activeToolCalls.delete(msg.toolName === 'load_skill' ? msg.skillName! : msg.toolName);
    this.displayItems = [...this.displayItems];
    host.cdr.markForCheck();
  }

  processMessageForDisplay(host: AgentChatDisplayHost, msg: ChatMessage): void {
    if (msg.isUser) {
      this.addDisplayItem(host, { kind: 'message', msg });
      return;
    }

    const organizerGuid = agentGateway.getOrganizerGuid();
    if (organizerGuid && msg.guid === organizerGuid) {
      return;
    }

    if (msg.toolName === 'get_planned_routes_data') {
      return;
    }

    if (
      msg.result &&
      (msg.result.beginRendering || msg.result.surfaceUpdate) &&
      (msg.result.beginRendering?.surfaceId === 'route_list' ||
        msg.result.surfaceUpdate?.surfaceId === 'route_list')
    ) {
      return;
    }

    switch (msg.msgType) {
      case AgentMessageType.SYSTEM:
        this.addDisplayItem(host, {
          kind: 'system',
          msg,
        });
        return;

      case AgentMessageType.RUN_START:
        return;

      case AgentMessageType.RUN_END:
        if (msg.guid === host.agents[host.currentAgent!.agentType]) {
          host.isAgentWorking = false;
        }

        host.isSecuringAgent = false;

        return;

      case AgentMessageType.MODEL_START:
        return;

      case AgentMessageType.MODEL_END:
        if (host.finalToolCallMessage) {
          this.displayItems = [...this.displayItems, host.finalToolCallMessage];
        }

        if (msg.text && msg.speaker.toLowerCase() === 'planner_with_memory') {
          this.displayItems = [
            ...this.displayItems,
            {
              msg,
              kind: 'message',
            },
          ];
        }

        return;

      case AgentMessageType.TOOL_START:
        if (host.filterSettings.showToolCalls && msg.toolName) {
          const idx = this.displayItems.length;
          this.addDisplayItem(host, {
            kind: 'tool_call',
            msg: {
              ...msg,
              toolName: msg.skillName ? `${msg.toolName}: ${msg.skillName}` : msg.toolName,
              text: `tool start : ${msg.toolName}`,
            },
          });
          this.activeToolCalls.set(
            msg.toolName === 'load_skill' ? msg.skillName! : msg.toolName,
            idx,
          );
        }

        return;
      case AgentMessageType.TOOL_END:
        if (msg.result && msg.result.surfaceUpdate) {
          this.addDisplayItem(host, { kind: 'a2ui', node: msg.result });
          return;
        }

        if (msg.toolName === 'set_financial_modeling_mode') {
          this.displayItems = [];

          host.chatMessages = [];
          this.expandedToolCalls.clear();
          this.activeToolCalls.clear();

          const activeDemoKey = host.demoService.activeDemo();
          const activeDemo = DEMO_CONFIG[activeDemoKey] as {
            promptPlaceholder?: string;
          };

          if (activeDemo.promptPlaceholder) {
            if (host.chatTextAreaRef) {
              host.chatTextAreaRef.nativeElement.value = activeDemo.promptPlaceholder;
            }
            host.chatInput = activeDemo.promptPlaceholder;
            if (host.chatTextAreaRef) {
              host.autoResize();
            }
          }
        }

        if (msg.toolName === 'fire_start_gun') {
          host.resetSimulationStatistics();

          host.handleRaceStarted();
        }

        if (msg.toolName === 'advance_tick') {
          host.handleTickUpdate(msg.result as Record<string, unknown>);
          return;
        }

        if (host.filterSettings.showToolCalls) {
          if (
            (msg.toolName && this.activeToolCalls.has(msg.toolName)) ||
            (msg.toolName === 'load_skill' && this.activeToolCalls.has(msg.skillName!))
          )
            this.finishToolCall(host, msg);
          return;
        }

        return;
      case AgentMessageType.TOOL_ERROR:
        if (host.filterSettings.showToolCalls) {
          if (msg.speaker.includes(demoFiveSpeaker)) {
            const idx = this.activeToolCalls.get('prepare_simulation');
            if (idx === undefined) return;
            const item = this.displayItems[idx];
            if (!item || item.kind !== 'tool_call') return;
            if (host.demoService.activeDemo() === '5a') {
              setTimeout(() => {
                this.setToolCallToWarning(host);
              }, 1000);

              return;
            }

            item.done = true;
            item.error = true;
            item.msg = { ...item.msg, text: this.displayText(msg) };
            this.activeToolCalls.delete('prepare_simulation');
            this.displayItems = [...this.displayItems];
          }
        }

        host.isAgentWorking = false;

        this.addDisplayItem(host, { kind: 'message', msg });

        if (msg.speaker.toLowerCase().includes(demoFiveSpeaker)) {
          if (host.demoService.activeDemo() === '5a') {
            return;
          }

          let count = 0;

          host.errorMessageInterval = window.setInterval(() => {
            if (count >= 15) {
              clearInterval(host.errorMessageInterval as number);
            }

            if (count === 3) {
              window.dispatchEvent(new CustomEvent('sim:reset'));
              window.dispatchEvent(new CustomEvent('sim:triggerError'));
            }

            this.addDisplayItem(host, { kind: 'message', msg });
            host.cdr.markForCheck();
            setTimeout(() => host.scrollChatToBottom(), 0);
            count++;
          }, 1000);
        }

        return;

      case AgentMessageType.INTER_AGENT:
        this.addDisplayItem(host, {
          kind: 'message',
          msg,
        });
        return;
      case AgentMessageType.TEXT:
        this.addDisplayItem(host, {
          msg,
          kind: 'message',
        });

        return;
      case AgentMessageType.AGENT_START:
        return;
      case AgentMessageType.AGENT_END:
        return;
      case AgentMessageType.MODEL_ERROR:
        this.displayItems = [...this.displayItems, { kind: 'message', msg }];
        if (msg.guid === host.agents[host.currentAgent!.agentType]) {
          host.isAgentWorking = false;
        }
        return;
      default:
        console.warn('Message Type not implemented:', msg.msgType);
    }
  }
}
