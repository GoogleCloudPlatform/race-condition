/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import type { ChangeDetectorRef, ElementRef } from '@angular/core';
import type { AnimationEvent } from '@angular/animations';
import type { ChatMessage } from '../../../../gateway.service';
import type { DemoService } from '../../../DemoOverlay/demo.service';
import type { DisplayItem } from './agent-screen.types';
import type { AgentChatDisplayService } from './services/agent-chat-display.service';

/**
 * Narrow surface passed to Agent tab child components (replaces `AgentScreenComponent` in `@Input()` types).
 */
export interface AgentScreenHost {
  readonly chatDisplay: AgentChatDisplayService;
  readonly demoService: DemoService;
  readonly cdr: ChangeDetectorRef;

  chatMessages: ChatMessage[];
  chatInput: string;
  chatTextAreaRef?: ElementRef<HTMLTextAreaElement>;
  agents: Record<string, string | null>;
  currentAgent: { agentType: string; sessionId: string } | null;
  filterSettings: { showToolCalls: boolean; showLoadSkills: boolean };
  isSecuringAgent: boolean;
  isAgentWorking: boolean;
  finalToolCallMessage: DisplayItem | null;
  errorMessageInterval: number | null;

  get displayItems(): DisplayItem[];
  get expandedToolCalls(): Set<number>;

  get chatInputPlaceholder(): string;
  get canSend(): boolean;
  get secureMode(): boolean;
  get cloudAssistMode(): boolean;

  settingsOpen: boolean;
  agentGatewayMsgDumpCanDownload: boolean;
  readonly agentGatewayMsgDebugDownload: () => void;
  runCachedMessages: boolean;
  activeDemoHasRecordingConfig: boolean;
  cachedMessageTimeScale: number;
  isSecurityDemo: boolean;
  isIntentToInfrastructureDemo: boolean;

  onSettingsButtonClick(): void;
  setRunCachedMessages(value: boolean, options?: { showModeFeedback?: boolean }): Promise<void>;
  onCachedMessageTimeScaleChange(value: string | number): void;
  setPlannerSecurity(secure: boolean): void;
  setCloudAssistMode(value: boolean): Promise<void>;
  clampSnapCachedMessageTimeScale(value: number): number;

  setActiveTab(tab: 'agent' | 'organizer' | 'log'): void;
  onTabLabelAnimationDone(event: AnimationEvent): void;
  togglePanelExpanded(): void;

  onChatScroll(event?: Event): void;
  toggleToolCall(idx: number): void;
  onSend(): void;
  autoResize(): void;
}
