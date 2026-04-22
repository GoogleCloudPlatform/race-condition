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

import {
  Component,
  OnInit,
  OnDestroy,
  NgZone,
  ChangeDetectorRef,
  ViewChild,
  ElementRef,
  HostListener,
  ChangeDetectionStrategy,
  effect,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { type AnimationEvent } from '@angular/animations';
import { Subscription } from 'rxjs';
import { GatewayService, ChatMessage } from '../../../../gateway.service';
import { LogComponent } from '../Log/log.component';
import { OrganizerComponent } from '../Organizer/organizer.component';
import { SimulationPanelComponent } from './SimulationPanel/simulation-panel.component';

import { DEMO_CONFIG, PRECONFIGURED_ROUTES } from '../../../../demo-config';
import { AgentMessageType } from '../../../../types';
import { DemoService } from '../../../DemoOverlay/demo.service';
import { simulationState } from '../../../../simulation-state';

import { downloadAgentGatewayMessageDump } from '../../../../../../agent-gateway-message-dump';
import type { DisplayItem, PathEntry, RouteCard, SimRunner, SyncPayload } from './agent-screen.types';
import {
  AgentChatDisplayService,
  type AgentChatDisplayHost,
} from './services/agent-chat-display.service';
import { AgentDemoSessionService } from './services/agent-demo-session.service';
import {
  AgentCachedGatewayReplayService,
  type AgentCachedGatewayReplayHost,
} from './services/agent-cached-gateway-replay.service';
import { TAB_ANIM_PILL_MS } from './agent-screen.constants';
import type { AgentScreenHost } from './agent-screen-host.model';
import { AgentSimulationStatsService } from './services/agent-simulation-stats.service';
import { AgentPanelTabExpansionService } from './services/agent-panel-tab-expansion.service';
import { AgentGatewayAgentsService } from './services/agent-gateway-agents.service';
import {
  AgentWindowEventsService,
  type AgentWindowEventsScreenBridge,
} from './services/agent-window-events.service';
import { AgentChatPanelComponent } from './agent-chat-panel/agent-chat-panel.component';
import { AgentPanelHeaderComponent } from './agent-panel-header/agent-panel-header.component';
import { AgentChatComposerComponent } from './agent-chat-composer/agent-chat-composer.component';

export type { PathEntry } from './agent-screen.types';

@Component({
  selector: 'agent-screen',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    OrganizerComponent,
    LogComponent,
    SimulationPanelComponent,
    AgentChatPanelComponent,
    AgentPanelHeaderComponent,
  ],
  providers: [
    AgentSimulationStatsService,
    AgentPanelTabExpansionService,
    AgentGatewayAgentsService,
    AgentWindowEventsService,
    AgentChatDisplayService,
    AgentDemoSessionService,
    AgentCachedGatewayReplayService,
  ],
  templateUrl: './agent-screen.component.html',
  styleUrls: ['./agent-screen.scss'],
  host: {
    '[style.--agent-tab-pill-transition-ms]': `'${TAB_ANIM_PILL_MS}ms'`,
  },
})
export class AgentScreenComponent
  implements
    OnInit,
    OnDestroy,
    AgentScreenHost,
    AgentChatDisplayHost,
    AgentCachedGatewayReplayHost,
    AgentWindowEventsScreenBridge
{
  @ViewChild('fileInput') fileInputRef!: ElementRef<HTMLInputElement>;
  @ViewChild('debugChatScroll') debugChatScrollRef!: ElementRef<HTMLDivElement>;
  @ViewChild(AgentChatComposerComponent) private chatComposer?: AgentChatComposerComponent;
  @ViewChild(AgentChatPanelComponent) private chatPanel?: AgentChatPanelComponent;

  readonly simulation = inject(AgentSimulationStatsService);
  readonly panelTab = inject(AgentPanelTabExpansionService);
  readonly gatewayAgents = inject(AgentGatewayAgentsService);
  private readonly windowEvents = inject(AgentWindowEventsService);

  get showSimPanel(): boolean {
    return this.simulation.showSimPanel;
  }
  set showSimPanel(v: boolean) {
    this.simulation.showSimPanel = v;
  }

  get isExpanded(): boolean {
    return this.panelTab.isExpanded;
  }
  set isExpanded(v: boolean) {
    this.panelTab.isExpanded = v;
  }

  get activeTab(): 'agent' | 'organizer' | 'log' {
    return this.panelTab.activeTab;
  }
  set activeTab(v: 'agent' | 'organizer' | 'log') {
    this.panelTab.activeTab = v;
  }

  get tabBtnWide(): boolean {
    return this.panelTab.tabBtnWide;
  }
  set tabBtnWide(v: boolean) {
    this.panelTab.tabBtnWide = v;
  }

  get showTabLabels(): boolean {
    return this.panelTab.showTabLabels;
  }

  get runnersFinishedAwaitingHud(): Set<string> {
    return this.simulation.runnersFinishedAwaitingHud;
  }

  get agents(): Record<string, string | null> {
    return this.gatewayAgents.agents;
  }

  get initializingAgents(): Record<string, boolean> {
    return this.gatewayAgents.initializingAgents;
  }

  simulationId: string | null = null;
  errorMessageInterval: number | null = null;

  private _isAgentWorking = false;
  private dotsTimer?: ReturnType<typeof setInterval>;
  private dotsState = 0;

  private _forceLoading = false;

  get isAgentWorking(): boolean {
    return this._isAgentWorking || this._forceLoading;
  }
  set isAgentWorking(val: boolean) {
    this._isAgentWorking = val;
    this.cdr.markForCheck();
    if (val && !this.dotsTimer) {
      this.dotsState = 1;
      this.loadingMessage = 'Thinking.';
      this.dotsTimer = setInterval(() => {
        this.dotsState = (this.dotsState % 3) + 1;
        this.loadingMessage = 'Thinking' + '.'.repeat(this.dotsState);
        this.cdr.markForCheck();
      }, 400);
    } else if (!val && this.dotsTimer) {
      clearInterval(this.dotsTimer);
      this.dotsTimer = undefined;
      this.loadingMessage = 'Thinking...';
    }
  }

  currentAgent: {
    agentType: string;
    sessionId: string;
  } | null = null;

  paths: PathEntry[] = [];
  selectedId: number | null = null;

  chatMessages: ChatMessage[] = [];
  chatInput = '';
  simSpeed = 1;
  chatAtBottom = true;

  get displayItems(): DisplayItem[] {
    return this.chatDisplay.displayItems;
  }
  get expandedToolCalls(): Set<number> {
    return this.chatDisplay.expandedToolCalls;
  }

  currentDemoCachedRunCount = 0;

  loadingMessage = 'Thinking...';

  get chatInputPlaceholder(): string {
    if (this.isAgentWorking) {
      return this.loadingMessage;
    }
    return 'Write something here';
  }

  toggleToolCall(idx: number): void {
    this.chatDisplay.toggleToolCall(idx);
    this.cdr.markForCheck();
  }

  get isSimulationRunning(): boolean {
    return this.simulation.isSimulationRunning;
  }

  get simulationProgress(): number {
    return this.simulation.simulationProgress;
  }

  get averageDistance(): number {
    return this.simulation.averageDistance;
  }

  get numberOfFinishers(): number {
    return this.simulation.numberOfFinishers;
  }

  get numberOfActiveRunners(): number {
    return this.simulation.numberOfActiveRunners;
  }

  get averagePace(): string {
    return this.simulation.averagePace;
  }

  get isFollowingLeader(): boolean {
    return this.simulation.isFollowingLeader;
  }

  isSecurityDemo = false;
  isBuildAgentsDemo = false;
  isIntentToInfrastructureDemo = false;
  activeDemoHasRecordingConfig = false;
  runCachedMessages = true;

  cachedMessageTimeScale = 1;

  filterSettings = {
    showToolCalls: true,
    showLoadSkills: false,
  };

  settingsOpen = false;

  readonly agentGatewayMsgDebugDownload = downloadAgentGatewayMessageDump;

  agentGatewayMsgDumpCanDownload = false;

  isSecuringAgent = false;

  private _secureMode = false;
  get secureMode(): boolean {
    return this._secureMode;
  }
  clampSnapCachedMessageTimeScale(value: number): number {
    const c = Math.min(10, Math.max(0.5, value));
    return Math.round(c * 2) / 2;
  }

  onCachedMessageTimeScaleChange(value: string | number): void {
    const n = typeof value === 'string' ? parseFloat(value) : value;
    if (!Number.isFinite(n)) return;
    const next = this.clampSnapCachedMessageTimeScale(n);
    if (next === this.cachedMessageTimeScale) return;
    this.cachedMessageTimeScale = next;
    this.cdr.markForCheck();
  }

  async setSecureMode(value: boolean) {
    if (value) {
      this.demoService.select('7b');
    } else {
      this.demoService.select('7a');
    }

    this._secureMode = value;
    this.cdr.markForCheck();
    this.scheduleSegmentThumbsLayout();
  }

  setPlannerSecurity(secure: boolean) {
    if (this._secureMode === secure) return;
    void this.setSecureMode(secure);
  }

  private _cloudAssistMode = false;
  get cloudAssistMode(): boolean {
    return this._cloudAssistMode;
  }

  async setRunCachedMessages(value: boolean, options?: { showModeFeedback?: boolean }) {
    if (value && !this.activeDemoHasRecordingConfig) return;
    this.runCachedMessages = value;
    this.scheduleSegmentThumbsLayout();
    if (options?.showModeFeedback) {
      this.demoService.showModeSwitchFeedback(value);
    }
  }

  async setCloudAssistMode(value: boolean) {
    if (value) {
      this.demoService.select('5b');
    } else {
      this.demoService.select('5a');
    }

    this._cloudAssistMode = value;
    this.cdr.markForCheck();
    this.scheduleSegmentThumbsLayout();
  }

  applyDemoSessionCloudAssistShell(on: boolean): void {
    this._cloudAssistMode = on;
  }

  applyDemoSessionSecureShell(on: boolean): void {
    this._secureMode = on;
  }

  onCachedReplayComplete(): void {
    this.isAgentWorking = false;
    this.currentDemoCachedRunCount++;
  }

  onSettingsButtonClick(): void {
    this.settingsOpen = !this.settingsOpen;
    if (this.settingsOpen) {
      this.scheduleSegmentThumbsLayout();
    }
  }

  @HostListener('window:resize')
  onWindowResize(): void {
    if (this.settingsOpen) {
      this.layoutSegmentThumbs();
    }
  }

  scheduleSegmentThumbsLayout(): void {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        this.layoutSegmentThumbs();
      });
    });
  }

  private layoutSegmentThumbs(): void {
    const root = this.hostEl.nativeElement as HTMLElement;
    const toggles = root.querySelectorAll('.agent-settings-menu__toggle');
    toggles.forEach((toggle) => {
      const t = toggle as HTMLElement;
      const track = t.querySelector('.agent-settings-menu__toggle-track') as HTMLElement | null;
      if (!track) return;
      const pos = t.getAttribute('data-thumb-pos');
      if (pos !== 'left' && pos !== 'right') return;
      const buttons = track.querySelectorAll('.agent-settings-menu__toggle-segment');
      if (buttons.length !== 2) return;
      const seg = buttons[pos === 'left' ? 0 : 1] as HTMLButtonElement;
      const trackRect = track.getBoundingClientRect();
      const segRect = seg.getBoundingClientRect();
      const x = segRect.left - trackRect.left;
      const w = segRect.width;
      track.style.setProperty('--thumb-x', `${x}px`);
      track.style.setProperty('--thumb-w', `${w}px`);
    });
  }

  showLandmarks = false;
  showStreetNames = true;
  roadMode: 'off' | 'on' | 'color' = 'color';
  roadModeOptions = [
    { label: 'Off', value: 'off' as const },
    { label: 'On', value: 'on' as const },
    { label: 'Color coded', value: 'color' as const },
  ];

  finalToolCallMessage: DisplayItem | null = null;

  routeCards = new Map<string, RouteCard>();

  simRunners: SimRunner[] = [];
  focusedSimRunnerId: string | null = null;

  private subs: Subscription[] = [];

  demoService = inject(DemoService);
  readonly chatDisplay = inject(AgentChatDisplayService);
  readonly demoSession = inject(AgentDemoSessionService);
  private readonly cachedGatewayReplay = inject(AgentCachedGatewayReplayService);
  private readonly hostEl = inject(ElementRef);
  resetCounter = 0;

  get chatTextAreaRef(): ElementRef<HTMLTextAreaElement> | undefined {
    return this.chatComposer?.textAreaRef;
  }

  constructor(
    private ngZone: NgZone,
    public cdr: ChangeDetectorRef,
    public gateway: GatewayService,
  ) {
    effect(() => {
      const n = this.demoService.cachedMessagesToggle();
      if (n === 0) return;
      void this.setRunCachedMessages(!this.runCachedMessages, {
        showModeFeedback: true,
      });
    });

    effect(async () => {
      this.resetCounter = this.demoService.reset();
      void this.demoService.activeDemo();
      void this.demoService.cachedMessagesToggle();
      await this.demoSession.runDemoLifecycle(this);
    });
  }

  ngOnInit(): void {
    this.simulation.connect(this.cdr);
    this.panelTab.connect(this.cdr, () => {
      setTimeout(() => this.chatComposer?.autoResize(), 0);
    });
    this.gatewayAgents.connect(this.cdr);
    this.windowEvents.bind(this);
    this.windowEvents.seedGatewayDumpFlag();
    this.windowEvents.start();

    if (new URLSearchParams(window.location.search).get('loading') === 'true') {
      this._forceLoading = true;
      this.isAgentWorking = true;
    }

    this.subs.push(
      this.gateway.chat$.subscribe((msg: ChatMessage) => {
        const organizerGuid = this.gateway.getOrganizerGuid();
        if (!organizerGuid || msg.guid !== organizerGuid) {
          this.chatMessages = [...this.chatMessages, msg];
        }
        this.processMessageForDisplay(msg);
        this.cdr.markForCheck();
        if (this.chatAtBottom) {
          setTimeout(() => this.scrollChatToBottom(), 0);
        }
      }),
    );
  }

  ngOnDestroy(): void {
    if (this.dotsTimer) clearInterval(this.dotsTimer);
    this.panelTab.clearAnimationTimers();
    this.windowEvents.stop();
    this.simulation.dispose();
    this.subs.forEach((s) => s.unsubscribe());
    simulationState.deactivate();
    this.removeAllActiveAgents();
    this.stopCachedDataStream();
  }

  async runCachedDataStream(): Promise<void> {
    await this.cachedGatewayReplay.run(this);
  }

  stopCachedDataStream(): void {
    this.cachedGatewayReplay.stop();
  }

  onSyncPayload(d: SyncPayload): void {
    this.paths = d.paths;
    this.selectedId = d.selectedId;
  }

  applyCameraIntroComplete(): void {
    const activeDemoKey = this.demoService.activeDemo();
    const activeDemo = DEMO_CONFIG[activeDemoKey];

    if (activeDemo.placeholderRoutes) {
      const routeJson = PRECONFIGURED_ROUTES[activeDemo.placeholderRoutes] as {
        route_data?: unknown;
      };
      const geojson = routeJson.route_data ?? routeJson;

      window.dispatchEvent(new CustomEvent('gateway:routeGeojson', { detail: { geojson } }));
    }
  }

  handleRaceStarted(): void {
    this.simulation.handleRaceStarted();
  }

  handleTickUpdate(d: Record<string, unknown>): void {
    this.simulation.handleTickUpdate(d);
  }

  getAgentDisplayName(agentType: string): string {
    return this.gatewayAgents.getAgentDisplayName(agentType);
  }

  onChatScroll(event?: Event): void {
    const el =
      (event?.target as HTMLElement | null | undefined) ??
      this.chatPanel?.getChatScrollNative() ??
      null;
    if (!el) return;
    this.chatAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  }

  scrollChatToBottom(): void {
    this.chatPanel?.scrollChatToBottom();
  }

  onSimFinished(): void {
    this.simulation.onSimFinished();
  }

  onFocusRunner(guid: string): void {
    window.dispatchEvent(new CustomEvent('hud:focusRunner', { detail: { guid } }));
  }

  setActiveTab(tab: 'agent' | 'organizer' | 'log'): void {
    this.panelTab.setActiveTab(tab);
  }

  onTabLabelAnimationDone(event: AnimationEvent): void {
    this.panelTab.onTabLabelAnimationDone(event);
  }

  onExpandFromSimulationPanel(): void {
    this.simulation.showSimPanel = false;
    this.panelTab.expandPanelAfterCollapsed();
  }

  togglePanelExpanded(): void {
    this.panelTab.togglePanelExpanded();
  }

  autoResize(): void {
    this.chatComposer?.autoResize();
  }

  onSend(): void {
    const text = this.chatInput.trim();

    if (!text || !this.canSend || this.isAgentWorking) return;

    if (this.runCachedMessages) {
      const activeDemoKey = this.demoService.activeDemo();
      const activeDemo = DEMO_CONFIG[activeDemoKey] as any;

      const message = {
        guid: '',
        speaker: 'You',
        isUser: true,
        msgType: AgentMessageType.SYSTEM,
        text: activeDemo.promptPlaceholder,
        timestamp: new Date(),
      };

      this.chatMessages = [message];
      this.processMessageForDisplay(message);

      void this.runCachedDataStream();
    } else {
      this.gateway.sendBroadcast(text, [this.agents[this.currentAgent!.agentType] as string]);
    }

    this.isAgentWorking = true;
    this.chatInput = '';
    this.chatComposer?.resetHeight();

    this.cdr.markForCheck();
  }

  onRemoveAgent(agentType: string): void {
    this.gatewayAgents.onRemoveAgent(agentType);
  }

  removeAllActiveAgents(): void {
    this.gatewayAgents.removeAllActiveAgents();
  }

  async onInitAgent(agentType: string): Promise<void> {
    await this.gatewayAgents.onInitAgent(agentType, this.runCachedMessages);
  }

  get canSend(): boolean {
    return (
      this.runCachedMessages ||
      (!!this.agents[this.currentAgent!.agentType] && Object.keys(this.agents).length > 0)
    );
  }

  processMessageForDisplay(msg: ChatMessage): void {
    this.chatDisplay.processMessageForDisplay(this, msg);
    this.cdr.markForCheck();
  }

  trackByDisplayItem(i: number, item: DisplayItem): string {
    return this.chatDisplay.trackByDisplayItem(i, item);
  }

  resetSimulationStatistics(): void {
    this.simulation.resetSimulationStatistics();
  }

  onFollowLeader(): void {
    this.simulation.onFollowLeader();
  }

  onFollowRandomRunner(): void {
    this.simulation.onFollowRandomRunner();
  }
}
