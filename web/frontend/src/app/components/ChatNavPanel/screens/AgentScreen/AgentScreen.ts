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
import { FormsModule } from '@angular/forms';
import { MarkdownPipe } from 'ngx-markdown';
import { trigger, style, transition, animate, type AnimationEvent } from '@angular/animations';
import { Subscription } from 'rxjs';
import { GatewayService, ChatMessage, BackendAgent } from '../../../../gateway.service';
import { LogComponent } from '../Log/Log';
import { OrganizerComponent } from '../Organizer/Organizer';
import { SimulationPanelComponent } from './SimulationPanel/SimulationPanel';

import { A2uiControllerComponent } from '../../../a2ui/a2-ui-controller';
import { SpinnerComponent } from '../../../Spinner/Spinner';
import { DEMO_CONFIG, PRECONFIGURED_ROUTES } from '../../../../demo-config';
import { AgentMessageType, ChatAgent } from '../../../../types';
import { DemoService } from '../../../DemoOverlay/demo.service';
import { simLog } from '../../../../sim-logger';

import {
  simulationState,
  type SimulationStateData,
  type SimulationSnapshot,
} from '../../../../simulation-state';
import {
  HARDCODED_SIM_DISTANCE_INTEGRATOR,
  HARDCODED_SIM_PROGRESS_WALL_MS,
  MARATHON_DISTANCE_MI,
} from '../../../../runner-sim-constants';

import {
  demoFiveSpeaker,
  SECURE_AGENT_PROMPT,
  UNSECURE_AGENT_PROMPT,
} from '../../../../../constants';
import {
  AGENT_GATEWAY_MSG_DUMP_CHANGED,
  agentGatewayMsgDumpLineCount,
  downloadAgentGatewayMessageDump,
  parseAgentGatewayMsgNdjsonInterFrameReplayMeta,
  parseAgentGatewayMsgNdjsonToInboundRecords,
  replayAgentGatewayMsgNdjsonText,
} from '../../../../../../agent-gateway-message-dump';
import { agentGateway } from '../../../../agent-gateway-updates';

interface RouteCard {
  id: string;
  name: string;
  distance: string;
  color: string;
  imageDataUrl: string;
  coords: [number, number][];
}

interface SimRunner {
  id: string;
  name: string;
  status: 'active' | 'finished' | 'did-not-finish';
  velocity: number;
  hydration: number;
  energy: number;
  percentComplete: number;
  color: string;
}

/** Race results summary shown after compile_results */
interface RaceResults {
  totalTicks: number;
  finalStatusCounts: Record<string, number>;
  notableEvents: string[];
  samplingQuality: number;
  avgRunnersReporting: number;
}

/** Standalone tick-progress card shown while a simulation is running */
interface TickProgressItem {
  kind: 'tick_progress';
  guid: string;
  tick: number;
  maxTicks: number;
  label: string;
  done: boolean;
}

/** Union type for display items in the chat list */
type DisplayItem =
  | { kind: 'system'; msg: ChatMessage }
  | { kind: 'message'; msg: ChatMessage }
  | { kind: 'route'; msg: ChatMessage; card: RouteCard }
  | { kind: 'a2ui'; node: any }
  | { kind: 'race_results'; msg: ChatMessage; results: RaceResults }
  | { kind: 'tool_call'; msg: ChatMessage; done?: boolean; error?: boolean; warning?: boolean }
  | TickProgressItem;

export interface PathEntry {
  id: number;
  name: string;
  lengthMi: number;
  colorHex: string;
  waterStationCount: number;
}

interface SyncPayload {
  paths: PathEntry[];
  selectedId: number | null;
}

/** Normalized course progress (0–1) from the viewport runner sim; crossing this counts one UI finisher. */
const FINISH_UI_PROGRESS_T = 0.999;

/** Backend velocity is normalized: real mph = velocity × SPEED_SCALE (6.2137). */
const PACE_SPEED_SCALE = 6.2137;

/**
 * Single tuning point for tab bar motion: pill width (CSS + setTimeout delays) and label enter duration.
 * Leave is slightly shorter than enter; change `TAB_ANIM_PILL_MS` only unless you want a custom ratio.
 */
const TAB_ANIM_PILL_MS = 125;
const TAB_ANIM_LABEL_LEAVE_MS = Math.round(TAB_ANIM_PILL_MS * 0.8);

@Component({
  selector: 'agent-screen',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    A2uiControllerComponent,
    SpinnerComponent,
    MarkdownPipe,
    OrganizerComponent,
    LogComponent,
    SimulationPanelComponent,
  ],
  styleUrls: ['./agent-screen.scss'],
  host: {
    '[style.--agent-tab-pill-transition-ms]': `'${TAB_ANIM_PILL_MS}ms'`,
  },
  animations: [
    trigger('tabLabel', [
      transition(':enter', [
        style({ opacity: 0, transform: 'translateY(-8px)' }),
        animate(
          `${TAB_ANIM_PILL_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`,
          style({ opacity: 1, transform: 'translateY(0)' }),
        ),
      ]),
      transition(':leave', [
        animate(
          `${TAB_ANIM_LABEL_LEAVE_MS}ms cubic-bezier(0.4, 0, 1, 1)`,
          style({ opacity: 0, transform: 'translateY(-8px)' }),
        ),
      ]),
    ]),
  ],
  template: `
    <!-- ── Left: Runners/Planner + Chat ──────────────────────────── -->
    <simulation-panel
      [hidden]="!showSimPanel"
      [simulationProgress]="simulationProgress"
      [averageDistance]="averageDistance"
      [numberOfFinishers]="numberOfFinishers"
      [averagePace]="averagePace"
      [isFollowingLeader]="isFollowingLeader"
      (followLeader)="onFollowLeader()"
      (followRandomRunner)="onFollowRandomRunner()"
      (expand)="onExpandFromSimulationPanel()"
    ></simulation-panel>
    <div [hidden]="showSimPanel">
      <!-- existing chat content -->

      <div class="panel-wrapper" [class.thinking]="isAgentWorking && activeTab === 'agent'">
        <div class="panel" [class.closed]="!isExpanded">
          <div class="wave-blur"><div class="wave-inner"></div></div>
          <!-- Panel title -->
          <div class="panel__header">
            <div class="panel__header__title">
              <div class="tab-bar">
                <button
                  class="tab-btn"
                  [disabled]="!isExpanded"
                  [class.active]="activeTab === 'agent'"
                  [class.tab-btn--wide]="activeTab === 'agent' && tabBtnWide"
                  (click)="setActiveTab('agent')"
                >
                  <spinner [spinning]="isAgentWorking"></spinner>
                  <span
                    *ngIf="activeTab === 'agent' && isExpanded && showTabLabels"
                    [@tabLabel]
                    (@tabLabel.done)="onTabLabelAnimationDone($event)"
                    >Agent</span
                  >
                </button>
                <button
                  class="tab-btn organizer"
                  [disabled]="!isExpanded"
                  [class.active]="activeTab === 'organizer'"
                  [class.tab-btn--wide]="activeTab === 'organizer' && tabBtnWide"
                  (click)="setActiveTab('organizer')"
                >
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path
                      fill-rule="evenodd"
                      clip-rule="evenodd"
                      d="M12.2175 4.12502C12.4909 3.44857 13.0015 2.89495 13.6537 2.56778C14.3058 2.24062 15.0548 2.16233 15.7606 2.34757C16.4663 2.53282 17.0803 2.9689 17.4877 3.57419C17.8951 4.17948 18.0679 4.91249 17.9738 5.63602C17.8798 6.35955 17.5253 7.024 16.9767 7.50501C16.4281 7.98602 15.7229 8.25061 14.9933 8.24927C14.2637 8.24792 13.5596 7.98072 13.0128 7.49769C12.4659 7.01465 12.1139 6.34889 12.0225 5.62502H7.5C6.90326 5.62502 6.33097 5.86207 5.90901 6.28403C5.48705 6.70598 5.25 7.27828 5.25 7.87502C5.25 8.47175 5.48705 9.04405 5.90901 9.46601C6.33097 9.88796 6.90326 10.125 7.5 10.125H18C18.9946 10.125 19.9484 10.5201 20.6516 11.2234C21.3549 11.9266 21.75 12.8805 21.75 13.875C21.75 14.8696 21.3549 15.8234 20.6516 16.5267C19.9484 17.2299 18.9946 17.625 18 17.625H9.7275C9.63612 18.3489 9.28406 19.0147 8.73723 19.4977C8.19041 19.9807 7.48629 20.2479 6.75667 20.2493C6.02705 20.2506 5.32195 19.986 4.77334 19.505C4.22473 19.024 3.87022 18.3595 3.77616 17.636C3.6821 16.9125 3.85494 16.1795 4.26233 15.5742C4.66972 14.9689 5.28374 14.5328 5.98945 14.3476C6.69516 14.1623 7.44419 14.2406 8.09635 14.5678C8.7485 14.895 9.25907 15.4486 9.5325 16.125H18C18.5967 16.125 19.169 15.888 19.591 15.466C20.0129 15.0441 20.25 14.4718 20.25 13.875C20.25 13.2783 20.0129 12.706 19.591 12.284C19.169 11.8621 18.5967 11.625 18 11.625H7.5C6.50544 11.625 5.55161 11.2299 4.84835 10.5267C4.14509 9.82341 3.75 8.86958 3.75 7.87502C3.75 6.88046 4.14509 5.92663 4.84835 5.22337C5.55161 4.52011 6.50544 4.12502 7.5 4.12502H12.2175Z"
                      fill="white"
                    />
                  </svg>
                  <span
                    *ngIf="activeTab === 'organizer' && isExpanded && showTabLabels"
                    [@tabLabel]
                    (@tabLabel.done)="onTabLabelAnimationDone($event)"
                    >Organizer</span
                  >
                </button>
                <button
                  class="tab-btn"
                  [disabled]="!isExpanded"
                  [class.active]="activeTab === 'log'"
                  [class.tab-btn--wide]="activeTab === 'log' && tabBtnWide"
                  (click)="setActiveTab('log')"
                >
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path
                      d="M4.70757 5.29292C4.51897 5.11076 4.26636 5.00997 4.00417 5.01224C3.74197 5.01452 3.49116 5.11969 3.30575 5.3051C3.12034 5.49051 3.01517 5.74132 3.0129 6.00352C3.01062 6.26571 3.11141 6.51832 3.29357 6.70692L8.58657 11.9999L3.29357 17.2929C3.19806 17.3852 3.12188 17.4955 3.06947 17.6175C3.01706 17.7395 2.98947 17.8707 2.98832 18.0035C2.98717 18.1363 3.01247 18.268 3.06275 18.3909C3.11303 18.5138 3.18728 18.6254 3.28117 18.7193C3.37507 18.8132 3.48672 18.8875 3.60962 18.9377C3.73251 18.988 3.86419 19.0133 3.99697 19.0122C4.12975 19.011 4.26097 18.9834 4.38297 18.931C4.50498 18.8786 4.61532 18.8024 4.70757 18.7069L10.7076 12.7069C10.895 12.5194 11.0004 12.2651 11.0004 11.9999C11.0004 11.7348 10.895 11.4804 10.7076 11.2929L4.70757 5.29292ZM12.0006 16.9999C11.7354 16.9999 11.481 17.1053 11.2935 17.2928C11.1059 17.4803 11.0006 17.7347 11.0006 17.9999C11.0006 18.2651 11.1059 18.5195 11.2935 18.707C11.481 18.8946 11.7354 18.9999 12.0006 18.9999H20.0006C20.2658 18.9999 20.5201 18.8946 20.7077 18.707C20.8952 18.5195 21.0006 18.2651 21.0006 17.9999C21.0006 17.7347 20.8952 17.4803 20.7077 17.2928C20.5201 17.1053 20.2658 16.9999 20.0006 16.9999H12.0006Z"
                      fill="white"
                    />
                  </svg>

                  <span
                    *ngIf="activeTab === 'log' && isExpanded && showTabLabels"
                    [@tabLabel]
                    (@tabLabel.done)="onTabLabelAnimationDone($event)"
                    >Log</span
                  >
                </button>
              </div>

              <!-- Settings button + dropdown -->
              <div class="settings-btn-wrapper">
                <div
                  [class.open]="settingsOpen"
                  (click)="onSettingsButtonClick()"
                  class="settings-click-handler"
                ></div>
                <button
                  class="settings-btn"
                  [disabled]="!isExpanded"
                  [class.open]="settingsOpen"
                  (click)="onSettingsButtonClick()"
                >
                  <span class="material-icons">settings</span>
                </button>
                <div class="settings-dropdown" *ngIf="settingsOpen">
                  <div class="settings-label">Settings</div>
                  <div class="settings-list">
                    <div
                      class="settings-row settings-row--inline settings-row--gateway-msg-download"
                    >
                      <p class="settings-row-caption">Keep latest demo recording</p>
                      <button
                        type="button"
                        class="settings-gateway-msg-download"
                        [disabled]="!agentGatewayMsgDumpCanDownload"
                        (click)="agentGatewayMsgDebugDownload()"
                      >
                        Download
                      </button>
                    </div>
                    <div class="settings-row settings-row--inline">
                      <p class="settings-row-caption">AI Connection</p>
                      <div
                        class="settings-toggle"
                        role="group"
                        aria-label="AI Connection"
                        [attr.data-thumb-pos]="runCachedMessages ? 'left' : 'right'"
                      >
                        <div class="track">
                          <div class="thumb"></div>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="runCachedMessages"
                            [disabled]="!activeDemoHasRecordingConfig"
                            (click)="setRunCachedMessages(true)"
                          >
                            Cached
                          </button>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="!runCachedMessages"
                            (click)="setRunCachedMessages(false)"
                          >
                            Live
                          </button>
                        </div>
                      </div>
                    </div>

                    <div
                      *ngIf="activeDemoHasRecordingConfig"
                      class="settings-row settings-row--inline"
                    >
                      <p class="settings-row-caption">Replay speed (×)</p>
                      <input
                        type="number"
                        class="settings-timescale-input"
                        min="0.5"
                        max="10"
                        step="0.5"
                        [ngModel]="cachedMessageTimeScale"
                        (ngModelChange)="onCachedMessageTimeScaleChange($event)"
                        aria-label="Cached message replay speed multiplier"
                      />
                    </div>

                    <div *ngIf="isSecurityDemo" class="settings-row settings-row--inline">
                      <p class="settings-row-caption">Planner security status</p>
                      <div
                        class="settings-toggle "
                        role="group"
                        aria-label="Planner security"
                        [attr.data-thumb-pos]="secureMode ? 'left' : 'right'"
                      >
                        <div class="track">
                          <div class="thumb"></div>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="secureMode"
                            (click)="setPlannerSecurity(true)"
                          >
                            Secure
                          </button>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="!secureMode"
                            (click)="setPlannerSecurity(false)"
                          >
                            Unsecure
                          </button>
                        </div>
                      </div>
                    </div>

                    <div
                      *ngIf="isIntentToInfrastructureDemo"
                      class="settings-row settings-row--inline"
                    >
                      <p class="settings-row-caption">Gemini Cloud Assist</p>
                      <div
                        class="settings-toggle "
                        role="group"
                        aria-label="Planner security"
                        [attr.data-thumb-pos]="cloudAssistMode ? 'left' : 'right'"
                      >
                        <div class="track">
                          <div class="thumb"></div>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="cloudAssistMode"
                            (click)="setCloudAssistMode(true)"
                          >
                            Upgrade
                          </button>
                          <button
                            type="button"
                            class="segment"
                            [attr.aria-pressed]="!cloudAssistMode"
                            (click)="setCloudAssistMode(false)"
                          >
                            Standard
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <button class="expand-btn" (click)="togglePanelExpanded()">
                <span class="material-icons">{{ isExpanded ? 'unfold_less' : 'unfold_more' }}</span>
              </button>
            </div>
          </div>

          <!-- Chat messages (shared, hidden on Cars tab) -->
          <div
            class="chat-messages-wrap"
            [class.active]="activeTab === 'agent'"
            [hidden]="activeTab !== 'agent'"
          >
            <div class="chat-messages" #chatScroll (scroll)="onChatScroll()">
              <ng-container
                *ngFor="let item of displayItems; let i = index; trackBy: trackByDisplayIdx"
              >
                <!-- System message -->
                <ng-container *ngIf="item.kind === 'system'">
                  <div class="system-message" [innerHTML]="item.msg.text | markdown | async"></div>
                </ng-container>
                <!-- Tool call message -->
                <ng-container *ngIf="item.kind === 'tool_call'">
                  <div class="tool-call" [class.expanded]="expandedToolCalls.has(i)">
                    <div class="header">
                      <div
                        class="status"
                        [class.error]="item.done && item.error"
                        [class.warning]="item.done && item.warning"
                      >
                        <span class="material-icons tool-call-error" *ngIf="item.done && item.error"
                          >close</span
                        >
                        <span
                          class="material-icons tool-call-warning"
                          *ngIf="item.done && item.warning"
                          >error_outline</span
                        >
                        <span
                          *ngIf="item.done && !item.warning && !item.error"
                          class="material-icons tool-call-done"
                          >check</span
                        >
                        <span *ngIf="!item.done" class="tool-call-loading"></span>
                      </div>
                      <div class="top-content">
                        <div class="information">
                          <span
                            class="tool-call-label"
                            [class.warning]="item.done && item.warning"
                            [class.error]="item.done && item.error"
                            >TOOL_CALL</span
                          >
                          <!-- <span class="chat-time">{{ item.msg.timestamp | date: 'h:mm a' }}</span> -->
                        </div>
                        <div class="title">
                          <h2 class="tool-call-name">{{ item.msg.toolName }}</h2>
                          <button *ngIf="item.done && item.msg.text" (click)="toggleToolCall(i)">
                            <span class="material-icons">expand_more </span>
                          </button>
                        </div>
                      </div>
                    </div>
                    <div class="inner">
                      <p
                        *ngIf="item.done && item.msg.text"
                        [innerHTML]="item.msg.text | markdown | async"
                      ></p>
                    </div>
                  </div>
                </ng-container>

                <!-- A2UI Component -->
                <ng-container *ngIf="item.kind === 'a2ui'">
                  <div class="a2ui-display-item">
                    <div class="a2ui-header"></div>
                    <a2ui-controller
                      [node]="item.node"
                      [alwaysExpandExpandableCards]="true"
                    ></a2ui-controller>
                  </div>
                </ng-container>

                <!-- User / system message -->
                <ng-container *ngIf="item.kind === 'message'">
                  <div
                    class="chat-msg"
                    [class.chat-msg--user]="item.msg.isUser"
                    [class.chat-msg--error]="item.msg.msgType === 'tool_error'"
                  >
                    <div class="chat-msg-header" *ngIf="item.msg.msgType === 'tool_error'">
                      <span class="error-icon">error_outline</span>
                      <h2>Error message</h2>
                      <!-- <span class="chat-time">{{ item.msg.timestamp | date: 'h:mm a' }}</span> -->
                    </div>
                    <div
                      class="chat-msg-main"
                      [class.chat-msg-main--inline]="item.msg.msgType !== 'tool_error'"
                    >
                      <div
                        class="chat-text"
                        [class.chat-text--error]="item.msg.msgType === 'tool_error'"
                        [innerHTML]="item.msg.text | markdown | async"
                      ></div>
                      <!-- <span class="chat-time" *ngIf="item.msg.msgType !== 'tool_error'">{{ 
                        item.msg.timestamp | date: 'h:mm a'
                      }}</span>-->
                    </div>
                    <!-- A2UI Controller for tool_end messages with a2ui data -->
                    <a2ui-controller
                      *ngIf="item.msg.msgType === 'tool_end' && item.msg.result"
                      [node]="item.msg.result"
                      [alwaysExpandExpandableCards]="true"
                    ></a2ui-controller>
                  </div>
                </ng-container>
              </ng-container>
            </div>

            <!-- Chat input (shared, hidden on Cars tab) -->
            <div class="panel__input" [class.panel__input--loading]="isAgentWorking">
              <div *ngIf="isAgentWorking" class="input-loader">
                <span class="input-loader__dot"></span>
                <span class="input-loader__dot"></span>
                <span class="input-loader__dot"></span>
              </div>
              <textarea
                #chatTextArea
                class="chat-input"
                rows="1"
                [placeholder]="chatInputPlaceholder"
                [(ngModel)]="chatInput"
                [disabled]="isAgentWorking"
                (keydown.enter)="onChatEnter($event)"
                (input)="autoResize()"
              ></textarea>
              <button
                class="send-button"
                (click)="onSend()"
                [disabled]="!chatInput.trim() || !canSend || isAgentWorking || isSecuringAgent"
              >
                <span class="material-icons">send</span>
              </button>
            </div>
          </div>

          <app-organizer
            [class.active]="activeTab === 'organizer'"
            [hidden]="activeTab !== 'organizer'"
            [runCachedMessages]="runCachedMessages"
          ></app-organizer>

          <app-log [class.active]="activeTab === 'log'" [hidden]="activeTab !== 'log'"></app-log>
        </div>
      </div>
    </div>
  `,
})
export class AgentScreenComponent implements OnInit, OnDestroy {
  @ViewChild('fileInput') fileInputRef!: ElementRef<HTMLInputElement>;
  @ViewChild('chatScroll') chatScrollRef!: ElementRef<HTMLDivElement>;
  @ViewChild('debugChatScroll') debugChatScrollRef!: ElementRef<HTMLDivElement>;
  @ViewChild('chatTextArea') chatTextAreaRef!: ElementRef<HTMLTextAreaElement>;

  activeTab: 'agent' | 'organizer' | 'log' = 'agent';

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
        this.dotsState = (this.dotsState + 1) % 4;
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

  // Paths panel
  paths: PathEntry[] = [];
  selectedId: number | null = null;

  // Chat
  chatMessages: ChatMessage[] = [];
  displayItems: DisplayItem[] = [];
  private tickItems = new Map<string, TickProgressItem>();
  chatInput = '';
  simSpeed = 1;
  chatAtBottom = true;
  workingGuids = new Set<string>();
  expandedToolCalls = new Set<number>();
  activeToolCalls = new Map<string, number>();

  currentDemoCachedRunCount = 0;

  loadingMessage = 'Thinking...';

  get chatInputPlaceholder(): string {
    if (this.isAgentWorking) {
      return this.loadingMessage;
    }
    return 'Write something here';
  }

  toggleToolCall(idx: number): void {
    if (this.expandedToolCalls.has(idx)) {
      this.expandedToolCalls.delete(idx);
    } else {
      this.expandedToolCalls.add(idx);
    }
  }

  showSimPanel = false;
  isSimulationRunning = false;
  simulationProgress = 0;
  private simProgressStartMs = 0;
  private simProgressRafId: number | null = null;

  averageDistance = 0;
  numberOfFinishers = 0;

  numberOfActiveRunners = 0;
  averagePace = '0:00';

  isFollowingLeader = false;

  isSecurityDemo = false;
  isBuildAgentsDemo = false;
  isIntentToInfrastructureDemo = false;
  /** True when {@link DEMO_CONFIG} for the active demo defines `recordingConfig`. */
  activeDemoHasRecordingConfig = false;
  runCachedMessages = true;

  /** Cached NDJSON replay speed; default from demo `recordingConfig.timeScale`, clamped 0.5–10 step 0.5. */
  cachedMessageTimeScale = 1;

  filterSettings = {
    showToolCalls: true,
    showLoadSkills: false,
  };

  /** Cancel fn from {@link replayAgentGatewayMsgNdjsonText}; cleared on destroy. */
  private cachedReplayStop?: () => void;

  private cachedCountdownTimer?: ReturnType<typeof setTimeout>;

  onFollowLeader(): void {
    this.isFollowingLeader = true;
    window.dispatchEvent(new CustomEvent('hud:followLeader'));
  }

  onFollowRandomRunner(): void {
    this.isFollowingLeader = false;
    window.dispatchEvent(new CustomEvent('hud:followRandomRunner'));
  }

  private readonly onFollowStopped = (): void => {
    this.ngZone.run(() => {
      this.isFollowingLeader = false;
      this.cdr.markForCheck();
    });
  };

  private readonly onRouteIntroComplete = (): void => {
    this.isExpanded = true;
  };

  private readonly onCameraIntroComplete = (): void => {
    this.ngZone.run(() => {
      const activeDemoKey = this.demoService.activeDemo();
      const activeDemo = DEMO_CONFIG[activeDemoKey];

      if (activeDemo.placeholderRoutes) {
        const routeJson = PRECONFIGURED_ROUTES[activeDemo.placeholderRoutes] as any;
        const geojson = routeJson.route_data ?? routeJson;

        window.dispatchEvent(new CustomEvent('gateway:routeGeojson', { detail: { geojson } }));
      }

      this.cdr.markForCheck();
    });
  };

  /** Backend `finished` seen first; HUD `hud:updateSimRunner` must then show finish before we count. */
  runnersFinishedAwaitingHud = new Set<string>();

  /** Latest normalized course progress (0–1) per runner from viewport `hud:updateSimRunner` only. */
  private runnerCourseProgressByGuid = new Map<string, number>();

  private readonly onHudUpdateSimRunnerForFinishers = (e: Event): void => {
    const d = (e as CustomEvent).detail as {
      guid?: string;
      progress?: number;
      status?: 'active' | 'finished' | 'did-not-finish';
      velocity?: number;
    };

    if (!d.guid) return;

    if (typeof d.progress !== 'number' || !Number.isFinite(d.progress)) return;

    this.ngZone.run(() => {
      const clamped = Math.min(1, Math.max(0, d.progress!));
      this.runnerCourseProgressByGuid.set(d.guid!, clamped);

      if (this.runnerCourseProgressByGuid.size > 0) {
        let sumT = 0;
        for (const t of this.runnerCourseProgressByGuid.values()) {
          sumT += t;
        }
        const avgT = sumT / this.runnerCourseProgressByGuid.size;
        this.averageDistance = Math.round(avgT * MARATHON_DISTANCE_MI * 10) / 10;
      }

      if (d.progress! >= FINISH_UI_PROGRESS_T) {
        if (!this.runnersFinishedAwaitingHud.has(d.guid!)) {
          this.runnersFinishedAwaitingHud.add(d.guid!);
          this.numberOfFinishers++;
        }
      }

      this.cdr.markForCheck();
    });
  };

  isExpanded = true;

  /** Wide tab pill (min-width); sequenced with {@link showTabLabels} on panel expand/collapse. */
  tabBtnWide = false;

  /** Tab text labels; hidden during pill grow, then hidden before shrink when collapsing. */
  showTabLabels = true;

  private panelCollapseInProgress = false;

  private showTabLabelsAfterGrowTimeoutId: ReturnType<typeof setTimeout> | null = null;

  private shrinkThenClosePanelTimeoutId: ReturnType<typeof setTimeout> | null = null;

  /** When set, the current tab is closing before switching to this target (expanded panel only). */
  private pendingTab: 'agent' | 'organizer' | 'log' | null = null;

  private tabSwitchAfterShrinkTimeoutId: ReturnType<typeof setTimeout> | null = null;

  // Settings menu
  settingsOpen = false;

  /** Same as `window.__csAgentGatewayMsgDebugDownload` (agent-gateway-message-dump). */
  readonly agentGatewayMsgDebugDownload = downloadAgentGatewayMessageDump;

  /** True when the in-memory gateway NDJSON buffer has at least one line (see agent-gateway-message-dump). */
  agentGatewayMsgDumpCanDownload = false;

  private readonly onAgentGatewayMsgDumpChanged = (e: Event): void => {
    const count = (e as CustomEvent<{ count?: number }>).detail?.count ?? 0;
    this.ngZone.run(() => {
      this.agentGatewayMsgDumpCanDownload = count > 0;
      this.cdr.markForCheck();
    });
  };

  isSecuringAgent = false;

  private _secureMode = false;
  get secureMode(): boolean {
    return this._secureMode;
  }
  private clampSnapCachedMessageTimeScale(value: number): number {
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
      // console.log('setting this.isSecuringAgent = true;');
      // this.isSecuringAgent = value;
      // this.gateway.sendBroadcast(
      //   SECURE_AGENT_PROMPT,
      //   [this.agents[this.currentAgent!.agentType] as string],
      //   true,
      // );
    } else {
      this.demoService.select('7a');

      // console.log('setting this.isSecuringAgent = true;');
      // this.isSecuringAgent = true;
      // this.gateway.sendBroadcast(
      //   UNSECURE_AGENT_PROMPT,
      //   [this.agents[this.currentAgent!.agentType] as string],
      //   true,
      // );
    }

    // const activeDemo = DEMO_CONFIG[this.demoService.activeDemo()] as any;
    // this.chatTextAreaRef.nativeElement.value = activeDemo.promptPlaceholder;
    // this.chatInput = activeDemo.promptPlaceholder;

    // if (value) {
    // }
    this._secureMode = value;
    this.cdr.markForCheck();
    this.scheduleSegmentThumbsLayout();
  }

  setPlannerSecurity(secure: boolean) {
    if (this._secureMode === secure) return;
    void this.setSecureMode(secure);
  }

  //
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

  onSettingsButtonClick(): void {
    console.log('button clicked');
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

  private scheduleSegmentThumbsLayout(): void {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        this.layoutSegmentThumbs();
      });
    });
  }

  private layoutSegmentThumbs(): void {
    const root = this.hostEl.nativeElement as HTMLElement;
    const toggles = root.querySelectorAll('.settings-toggle');
    toggles.forEach((toggle) => {
      const t = toggle as HTMLElement;
      const track = t.querySelector('.track') as HTMLElement | null;
      if (!track) return;
      const pos = t.getAttribute('data-thumb-pos');
      if (pos !== 'left' && pos !== 'right') return;
      const buttons = track.querySelectorAll('.segment');
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

  //

  showLandmarks = false;
  showStreetNames = true;
  roadMode: 'off' | 'on' | 'color' = 'color';
  roadModeOptions = [
    { label: 'Off', value: 'off' as const },
    { label: 'On', value: 'on' as const },
    { label: 'Color coded', value: 'color' as const },
  ];

  agents: Record<string, string | null> = {};
  initializingAgents: Record<string, boolean> = {};

  finalToolCallMessage: DisplayItem | null = null;

  // Planner
  routeCards = new Map<string, RouteCard>();

  // Simulator
  simRunners: SimRunner[] = [];
  focusedSimRunnerId: string | null = null;

  // Simulation state tracking
  simState: SimulationStateData = simulationState.getState();
  private simStateUnsub: (() => void) | null = null;

  private subs: Subscription[] = [];

  demoService = inject(DemoService);
  private readonly hostEl = inject(ElementRef);
  private resetCounter = 0;

  constructor(
    private ngZone: NgZone,
    private cdr: ChangeDetectorRef,
    private gateway: GatewayService,
  ) {
    // Register before demo-init effect: on Ctrl+L, update runCachedMessages first so
    // onInitAgent sees the post-toggle mode (cached→live must run addAgent, not early-return).
    effect(() => {
      const n = this.demoService.cachedMessagesToggle();
      if (n === 0) return;
      void this.setRunCachedMessages(!this.runCachedMessages, {
        showModeFeedback: true,
      });
    });

    effect(async () => {
      // Re-run full demo init when Ctrl+L bumps cachedMessagesToggle (DemoService).
      void this.demoService.cachedMessagesToggle();

      this.stopCachedDataStream();

      this.onSimFinished();
      this.resetSimulationStatistics();

      this.removeAllActiveAgents();

      this.gateway.removeCurrentSimulationId();

      this.showSimPanel = false;
      this.currentDemoCachedRunCount = 0;

      window.dispatchEvent(new CustomEvent('sim:fixError'));
      window.dispatchEvent(new CustomEvent('sim:removeRunnerThoughts'));

      if (this.errorMessageInterval) clearInterval(this.errorMessageInterval);

      this.displayItems = [];
      this.chatMessages = [];
      this.expandedToolCalls.clear();
      this.activeToolCalls.clear();

      window.dispatchEvent(new CustomEvent('hud:removeAllPaths'));

      this.displayItems = this.displayItems.filter((item) => item.kind !== 'tick_progress');

      // to generate reset
      this.resetCounter = this.demoService.reset();

      window.dispatchEvent(new CustomEvent('sim:reset'));

      if (this.agents['tick_agent']) this.agents['tick_agent'] = null;

      const activeDemoKey = this.demoService.activeDemo();
      const activeDemo = DEMO_CONFIG[activeDemoKey];

      this.isExpanded = activeDemoKey !== 'Sandbox';
      this.tabBtnWide = false;
      this.activeTab = 'agent';

      this.isSecurityDemo = activeDemo.isSecurityDemo || false;
      this.isBuildAgentsDemo = activeDemo.isBuildAgentsDemo || false;
      this.isIntentToInfrastructureDemo = activeDemo.isIntentToInfrastructureDemo || false;
      this.activeDemoHasRecordingConfig = !!activeDemo.recordingConfig;
      if (!this.activeDemoHasRecordingConfig) {
        this.runCachedMessages = false;
        this.stopCachedDataStream();
      }

      this.cachedMessageTimeScale = activeDemo.recordingConfig
        ? this.clampSnapCachedMessageTimeScale(activeDemo.recordingConfig.timeScale ?? 1)
        : 1;

      this.filterSettings.showLoadSkills = this.isBuildAgentsDemo;
      this.gateway.setFilterSettings({ showLoadSkills: this.filterSettings.showLoadSkills });
      // if (this.isSecurityDemo) this.setSecureMode(false);

      await this.onInitAgent(activeDemo.agent);

      // Guard against stale async continuations if the demo changed while awaiting
      if (this.demoService.activeDemo() !== activeDemoKey) return;

      Object.entries(this.agents).forEach(([agentType, guid]) => {
        if (activeDemo.agent !== agentType && guid) {
          this.gateway.removeAgent(guid);
          this.agents[agentType] = null;
        }
      });

      this.isAgentWorking = false;

      this.currentAgent = {
        agentType: activeDemo.agent as ChatAgent,
        sessionId: this.agents[activeDemo.agent] as string,
      };
      console.log(this.currentAgent);

      if (activeDemoKey === '5b') {
        window.dispatchEvent(new CustomEvent('sim:giveRunnerThoughts'));
        this._cloudAssistMode = true;
        this.scheduleSegmentThumbsLayout();
      }

      if (activeDemoKey === '7b') {
        this._secureMode = true;
        this.scheduleSegmentThumbsLayout();

        if (!this.runCachedMessages) {
          this.isSecuringAgent = true;
          this.gateway.sendBroadcast(
            SECURE_AGENT_PROMPT,
            [this.agents[this.currentAgent!.agentType] as string],
            true,
          );
        }
      } else if (activeDemoKey === '7a') {
        this._secureMode = false;
        this.scheduleSegmentThumbsLayout();

        if (!this.runCachedMessages) {
          this.isSecuringAgent = true;
          this.gateway.sendBroadcast(
            UNSECURE_AGENT_PROMPT,
            [this.agents[this.currentAgent!.agentType] as string],
            true,
          );
        }
      }

      // Placeholder route auto-import disabled — route is imported when
      // the backend returns the real route via get_route / add_medical_tents.
      if (activeDemoKey !== 'Sandbox' && activeDemo.placeholderRoutes) {
        const routeJson = PRECONFIGURED_ROUTES[activeDemo.placeholderRoutes] as any;
        const geojson = routeJson.route_data ?? routeJson;

        window.dispatchEvent(new CustomEvent('gateway:routeGeojson', { detail: { geojson } }));
      }

      if (activeDemo.placeholderAgentMessage) {
        const message = {
          ...activeDemo.placeholderAgentMessage,
          guid: this.currentAgent!.sessionId,
          speaker: this.currentAgent!.agentType as string,
        };

        this.chatMessages = [message];
        this.processMessageForDisplay(message);
      }

      if (activeDemo.promptPlaceholder) {
        if (this.chatTextAreaRef) {
          this.chatTextAreaRef.nativeElement.value = activeDemo.promptPlaceholder;
        }
        this.chatInput = activeDemo.promptPlaceholder;
        if (this.chatTextAreaRef) {
          this.autoResize();
        }
      } else {
        if (this.chatTextAreaRef) {
          this.chatTextAreaRef.nativeElement.value = '';
        }
        this.chatInput = '';
        if (this.chatTextAreaRef) {
          this.autoResize();
        }
      }

      // Activate simulation state tracking for simulator demos
      // Activate simulation state tracking for simulator demos
      simulationState.deactivate();
    });
  }

  runnersFinished = new Set();

  ngOnInit(): void {
    if (new URLSearchParams(window.location.search).get('loading') === 'true') {
      this._forceLoading = true;
      this.isAgentWorking = true;
    }

    this.agentGatewayMsgDumpCanDownload = agentGatewayMsgDumpLineCount() > 0;
    window.addEventListener(
      AGENT_GATEWAY_MSG_DUMP_CHANGED,
      this.onAgentGatewayMsgDumpChanged as EventListener,
    );

    window.addEventListener('hud:sync', this.onSync);
    window.addEventListener('viewport:followStopped', this.onFollowStopped);
    window.addEventListener('viewport:cameraIntroComplete', this.onCameraIntroComplete);
    window.addEventListener('viewport:routeIntroComplete', this.onRouteIntroComplete);

    window.addEventListener('sim:finished', this.onSimFinished);

    window.addEventListener('sim:raceStarted', this.onSimRaceStarted);

    window.addEventListener('hud:updateSimRunner', this.onHudUpdateSimRunnerForFinishers);
    window.addEventListener('gateway:routeGeojson', this.onRouteGeojson);
    window.addEventListener('sim:firstBatchAvgVelocity', this.onFirstBatchAvgVelocity);

    agentGateway.setUiNumberOfFinishersGetter(() => this.numberOfFinishers);

    this.simStateUnsub = simulationState.onChange((state) => {
      this.ngZone.run(() => {
        this.simState = state;
        this.cdr.markForCheck();
      });
    });

    this.subs.push(
      this.gateway.chat$.subscribe((msg: ChatMessage) => {
        this.chatMessages = [...this.chatMessages, msg];

        // Track working state strictly from run boundaries
        // if (!msg.isUser && msg.msgType) {
        //   if (msg.msgType === 'run_start') {
        //     this.workingGuids.add(msg.guid);
        //   } else if (msg.msgType === 'run_end') {
        //     this.workingGuids.delete(msg.guid);
        //   }

        // Route import is now handled by gateway:routeGeojson event listener
        // Build display items
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
    this.clearTabAnimationTimers();
    window.removeEventListener(
      AGENT_GATEWAY_MSG_DUMP_CHANGED,
      this.onAgentGatewayMsgDumpChanged as EventListener,
    );
    window.removeEventListener('hud:sync', this.onSync);
    window.removeEventListener('viewport:followStopped', this.onFollowStopped);
    window.removeEventListener('viewport:cameraIntroComplete', this.onCameraIntroComplete);
    window.removeEventListener('viewport:routeIntroComplete', this.onRouteIntroComplete);
    window.removeEventListener('gateway:routeGeojson', this.onRouteGeojson);
    window.removeEventListener('sim:finished', this.onSimFinished);
    window.removeEventListener('sim:raceStarted', this.onSimRaceStarted);
    window.removeEventListener('hud:updateSimRunner', this.onHudUpdateSimRunnerForFinishers);
    window.removeEventListener('sim:firstBatchAvgVelocity', this.onFirstBatchAvgVelocity);
    agentGateway.setUiNumberOfFinishersGetter(null);
    this.subs.forEach((s) => s.unsubscribe());
    this.simStateUnsub?.();
    simulationState.deactivate();
    this.removeAllActiveAgents();
    if (this.simProgressRafId) cancelAnimationFrame(this.simProgressRafId);
    this.stopCachedDataStream();
  }

  /**
   * Loads `public/assets/sim-run.ndjson` (URL `/assets/sim-run.ndjson` in dev and prod)
   * and feeds frames into {@link agentGateway.handleMessage} using recorded gaps (`t` deltas;
   * missing `t` uses 2s). Optional `timingScale` speeds up replay (e.g. `2` = 2×).
   */
  async runCachedDataStream(): Promise<void> {
    this.stopCachedDataStream();

    const activeDemoKey = this.demoService.activeDemo();
    const activeDemo = DEMO_CONFIG[activeDemoKey] as any;

    const url = activeDemo.recordingConfig.cachedMessageStreams[this.currentDemoCachedRunCount];

    let text: string;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      text = await res.text();
      const ct = res.headers.get('content-type') ?? '';
      if (ct.includes('text/html') || text.trimStart().startsWith('<!')) {
        throw new Error(
          'Got HTML instead of NDJSON (SPA fallback). Ensure the file exists under public/.',
        );
      }
    } catch (e) {
      console.error('[AgentScreen] cached gateway dump fetch failed', url, e);
      return;
    }

    agentGateway.setReplayPrimaryAgentTypeHint(activeDemo.agent as string);
    agentGateway.beginNdjsonReplay();

    this.scheduleCachedCountdown(text);

    this.cachedReplayStop = replayAgentGatewayMsgNdjsonText(
      (e) => agentGateway.handleMessage(e),
      text,
      {
        encodeSemanticLine: (rec) => agentGateway.encodeInboundRecordForReplay(rec),
        intervalMs: 2000,
        useRecordedPerformanceTimestamps: true,
        getTimingScale: () => this.cachedMessageTimeScale,
        onComplete: () => {
          agentGateway.endNdjsonReplay();
          this.isAgentWorking = false;
          this.currentDemoCachedRunCount++;
        },
      },
    );
  }

  private scheduleCachedCountdown(ndjsonText: string): void {
    this.clearCachedCountdownTimer();

    const records = parseAgentGatewayMsgNdjsonToInboundRecords(ndjsonText);
    let startIndex = records.findIndex(
      (r) => r.event === 'tool_end' && r.data['tool_name'] === 'process_tick',
    );
    if (startIndex < 0) {
      startIndex = records.findIndex(
        (r) => r.event === 'tool_end' && r.data['tool_name'] === 'fire_start_gun',
      );
    }
    if (startIndex <= 0) return;

    const meta = parseAgentGatewayMsgNdjsonInterFrameReplayMeta(ndjsonText, 2000);
    if (meta.delays.length < startIndex) return;

    const scale =
      this.cachedMessageTimeScale > 0 && Number.isFinite(this.cachedMessageTimeScale)
        ? this.cachedMessageTimeScale
        : 1;
    let cumulativeMs = 0;
    for (let i = 0; i < startIndex; i++) {
      const baseGap = meta.delays[i];
      const apply = meta.interFrameApplyTimingScale[i];
      cumulativeMs += apply ? baseGap / scale : baseGap;
    }

    const COUNTDOWN_LEAD_MS = 3000;
    const triggerInMs = Math.max(0, cumulativeMs - COUNTDOWN_LEAD_MS);
    this.cachedCountdownTimer = setTimeout(() => {
      this.cachedCountdownTimer = undefined;
      window.dispatchEvent(new Event('countdown:autoStart'));
    }, triggerInMs);
  }

  private clearCachedCountdownTimer(): void {
    if (this.cachedCountdownTimer !== undefined) {
      clearTimeout(this.cachedCountdownTimer);
      this.cachedCountdownTimer = undefined;
    }
  }

  /** Stops timed replay from {@link runCachedDataStream} (same as the prior `stop2` callback). */
  stopCachedDataStream(): void {
    this.clearCachedCountdownTimer();
    this.cachedReplayStop?.();
    this.cachedReplayStop = undefined;
    agentGateway.endNdjsonReplay();
  }

  private runProgressAnimation(): void {
    const elapsed = Date.now() - this.simProgressStartMs;
    const rawPct = Math.min(100, (elapsed / HARDCODED_SIM_PROGRESS_WALL_MS) * 100);
    this.simulationProgress = Math.round(rawPct * 100) / 100;

    this.cdr.markForCheck();
    if (this.simulationProgress < 100) {
      this.simProgressRafId = requestAnimationFrame(() => this.runProgressAnimation());
    } else {
      this.simProgressRafId = null;
    }
  }

  private handleRaceStarted(): void {
    window.dispatchEvent(
      new CustomEvent('sim:raceStarted', {
        detail: { speedMultiplier: 1, simDistanceIntegrator: HARDCODED_SIM_DISTANCE_INTEGRATOR },
      }),
    );

    this.showSimPanel = true;
    this.isSimulationRunning = true;
    this.simulationProgress = 0;
    this.simProgressStartMs = Date.now();
    if (this.simProgressRafId) {
      cancelAnimationFrame(this.simProgressRafId);
      this.simProgressRafId = null;
    }
    this.simProgressRafId = requestAnimationFrame(() => this.runProgressAnimation());
    this.cdr.markForCheck();
  }

  private formatPaceFromNormalizedAvgVelocity(avgVelocity: number): string {
    if (!avgVelocity || avgVelocity <= 0) return '0:00';
    const totalMinutes = 60 / (avgVelocity * PACE_SPEED_SCALE);
    const mins = Math.floor(totalMinutes);
    const secs = Math.round((totalMinutes % 1) * 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  private onFirstBatchAvgVelocity = (e: Event): void => {
    const d = (e as CustomEvent).detail as { avgVelocity?: number };
    const avg = d?.avgVelocity;
    if (avg === undefined || avg <= 0) return;
    this.ngZone.run(() => {
      this.averagePace = this.formatPaceFromNormalizedAvgVelocity(avg);
      this.cdr.markForCheck();
    });
  };

  private handleTickUpdate(d: Record<string, any>): void {
    if (this.runnerCourseProgressByGuid.size === 0) {
      const rawMi = Number(d['avg_distance']);
      this.averageDistance = Number.isFinite(rawMi) ? Math.round(rawMi * 10) / 10 : 0;
    }
    this.numberOfActiveRunners = d['runners_reporting'] ?? 0;

    this.averagePace = this.formatPaceFromNormalizedAvgVelocity(d['avg_velocity'] ?? 0);

    this.cdr.markForCheck();
  }

  private onSync = (e: Event): void => {
    const d = (e as CustomEvent).detail as SyncPayload;
    this.ngZone.run(() => {
      this.paths = d.paths;
      this.selectedId = d.selectedId;
      this.cdr.markForCheck();
    });
  };

  getAgentDisplayName(agentType: string) {
    // Check if the gateway has a backend-provided display name for this agent type.
    const sessions = this.gateway.getAgents();
    const session = sessions.find((s: BackendAgent) => s.agentType === agentType);
    if (session?.displayName) return session.displayName;
    // Fall back to the raw agent type when no display name is available.
    return agentType;
  }

  // Route import is handled by the lookdev viewport's onRouteGeojson listener.
  private onRouteGeojson = (_e: Event): void => {};

  onChatScroll(): void {
    if (!this.chatScrollRef) return;
    const el = this.chatScrollRef.nativeElement;
    this.chatAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  }

  private scrollChatToBottom(): void {
    if (this.chatScrollRef) {
      const el = this.chatScrollRef.nativeElement;
      el.scrollTop = el.scrollHeight;
    }
  }

  onSimRaceStarted = () => {
    this.ngZone.run(() => {
      this.resetSimulationStatistics();
      this.showSimPanel = true;
      this.isSimulationRunning = true;
      this.cdr.markForCheck();
    });
  };

  onSimFinished = () => {
    this.showSimPanel = false;
    this.isSimulationRunning = false;
  };

  isA2uiMessage(m: ChatMessage): boolean {
    try {
      const parsed = JSON.parse(m.text);

      if (parsed && parsed.a2ui) {
        return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  getA2uiNode(m: ChatMessage): any {
    try {
      const parsed = JSON.parse(m.text);

      // If a2ui is a string (double-stringified), parse it again
      if (typeof parsed.a2ui === 'string') {
        return JSON.parse(parsed.a2ui);
      }

      return parsed.a2ui || null;
    } catch (e) {
      // console.error('Error parsing a2ui node:', e);
      return null;
    }
  }

  // ── Runners panel ───────────────────────────────────────────────

  onFocusRunner(guid: string): void {
    window.dispatchEvent(new CustomEvent('hud:focusRunner', { detail: { guid } }));
  }

  onChatEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (ke.shiftKey) return;
    ke.preventDefault();
    this.onSend();
  }

  setActiveTab(tab: 'agent' | 'organizer' | 'log'): void {
    if (tab === this.activeTab) return;
    if (this.pendingTab === tab) return;

    if (!this.isExpanded) {
      this.pendingTab = null;
      this.activeTab = tab;
      if (tab === 'agent') {
        setTimeout(() => this.autoResize(), 0);
      }
      this.cdr.markForCheck();
      return;
    }

    if (this.pendingTab !== null) {
      this.pendingTab = tab;
      this.cdr.markForCheck();
      return;
    }

    if (!this.showTabLabels) {
      this.switchTabWithoutLabelClose(tab);
      return;
    }

    this.pendingTab = tab;
    this.showTabLabels = false;
    this.cdr.markForCheck();
  }

  /** When labels are not visible (e.g. mid grow), switch tabs without running the close animation. */
  private switchTabWithoutLabelClose(tab: 'agent' | 'organizer' | 'log'): void {
    this.clearTabAnimationTimers();
    this.pendingTab = null;
    this.activeTab = tab;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.cdr.markForCheck();
    if (tab === 'agent') {
      setTimeout(() => this.autoResize(), 0);
    }
    this.scheduleRevealTabLabelsAfterGrow();
  }

  private clearTabAnimationTimers(): void {
    if (this.showTabLabelsAfterGrowTimeoutId != null) {
      clearTimeout(this.showTabLabelsAfterGrowTimeoutId);
      this.showTabLabelsAfterGrowTimeoutId = null;
    }
    if (this.shrinkThenClosePanelTimeoutId != null) {
      clearTimeout(this.shrinkThenClosePanelTimeoutId);
      this.shrinkThenClosePanelTimeoutId = null;
    }
    if (this.tabSwitchAfterShrinkTimeoutId != null) {
      clearTimeout(this.tabSwitchAfterShrinkTimeoutId);
      this.tabSwitchAfterShrinkTimeoutId = null;
    }
  }

  private scheduleRevealTabLabelsAfterGrow(): void {
    if (this.showTabLabelsAfterGrowTimeoutId != null) {
      clearTimeout(this.showTabLabelsAfterGrowTimeoutId);
      this.showTabLabelsAfterGrowTimeoutId = null;
    }
    this.showTabLabelsAfterGrowTimeoutId = setTimeout(() => {
      this.showTabLabelsAfterGrowTimeoutId = null;
      this.ngZone.run(() => {
        this.showTabLabels = true;
        this.cdr.markForCheck();
      });
    }, TAB_ANIM_PILL_MS);
  }

  /** After the outgoing tab’s label has left and its pill has shrunk, activate the next tab and grow it. */
  private applyTabOpenAfterSwitch(): void {
    const next = this.pendingTab;
    if (next == null) return;
    this.pendingTab = null;
    this.activeTab = next;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.cdr.markForCheck();
    if (next === 'agent') {
      setTimeout(() => this.autoResize(), 0);
    }
    this.scheduleRevealTabLabelsAfterGrow();
  }

  /** Called when returning from the simulation full-screen panel to the chat panel. */
  onExpandFromSimulationPanel(): void {
    this.showSimPanel = false;
    this.expandPanelAfterCollapsed();
  }

  togglePanelExpanded(): void {
    if (this.isSimulationRunning) {
      this.showSimPanel = true;
      return;
    }
    if (this.isExpanded) {
      this.beginPanelCollapse();
    } else {
      this.expandPanelAfterCollapsed();
    }
  }

  /** Panel opens: grow tab pill first, then show labels (matches TAB_ANIM_PILL_MS / --agent-tab-pill-transition-ms). */
  private expandPanelAfterCollapsed(): void {
    this.clearTabAnimationTimers();
    this.pendingTab = null;
    this.panelCollapseInProgress = false;
    this.isExpanded = true;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.cdr.markForCheck();
    this.scheduleRevealTabLabelsAfterGrow();
  }

  /** Start collapse: labels leave first, then pill shrinks, then panel closes. */
  private beginPanelCollapse(): void {
    this.clearTabAnimationTimers();
    this.pendingTab = null;
    if (!this.showTabLabels) {
      this.tabBtnWide = false;
      this.cdr.markForCheck();
      this.shrinkThenClosePanelTimeoutId = setTimeout(() => {
        this.shrinkThenClosePanelTimeoutId = null;
        this.ngZone.run(() => {
          this.isExpanded = false;
          this.cdr.markForCheck();
        });
      }, TAB_ANIM_PILL_MS);
      return;
    }
    this.panelCollapseInProgress = true;
    this.showTabLabels = false;
    this.cdr.markForCheck();
  }

  onTabLabelAnimationDone(event: AnimationEvent): void {
    if (event.triggerName !== 'tabLabel' || event.phaseName !== 'done') return;
    // Leave ends with toState `void`; enter completion has fromState `void` — ignore the latter.
    if (event.toState !== 'void' || event.fromState === 'void') return;

    if (this.pendingTab !== null) {
      this.tabBtnWide = false;
      this.cdr.markForCheck();
      this.tabSwitchAfterShrinkTimeoutId = setTimeout(() => {
        this.tabSwitchAfterShrinkTimeoutId = null;
        this.ngZone.run(() => this.applyTabOpenAfterSwitch());
      }, TAB_ANIM_PILL_MS);
      return;
    }

    if (!this.panelCollapseInProgress) return;
    this.panelCollapseInProgress = false;
    this.tabBtnWide = false;
    this.cdr.markForCheck();
    this.shrinkThenClosePanelTimeoutId = setTimeout(() => {
      this.shrinkThenClosePanelTimeoutId = null;
      this.ngZone.run(() => {
        this.isExpanded = false;
        this.cdr.markForCheck();
      });
    }, TAB_ANIM_PILL_MS);
  }

  autoResize(): void {
    const textarea = this.chatTextAreaRef?.nativeElement;
    if (!textarea) return;
    // const maxHeight = Infinity;
    textarea.style.height = 'auto';
    const next = textarea.scrollHeight; //Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${next}px`;
    // textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
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

      this.runCachedDataStream();
    } else {
      this.gateway.sendBroadcast(text, [this.agents[this.currentAgent!.agentType] as string]);
    }

    this.isAgentWorking = true;
    this.chatInput = '';
    const textarea = this.chatTextAreaRef?.nativeElement;
    if (textarea) textarea.style.height = 'auto';

    this.cdr.markForCheck();
  }

  onRemoveAgent(agentType: string): void {
    const guid = this.agents[agentType];
    if (guid) this.gateway.removeAgent(guid);
    this.agents[agentType] = null;
    this.cdr.markForCheck();
  }

  removeAllActiveAgents(): void {
    Object.entries(this.agents).forEach(([agentType, guid]) => {
      if (guid) this.gateway.removeAgent(guid);
      this.agents[agentType] = null;
    });
    this.initializingAgents = {};
    this.cdr.markForCheck();
  }

  async onInitAgent(agentType: string): Promise<void> {
    console.time('initialize agent');
    if (this.runCachedMessages) return;
    if (this.agents[agentType] || this.initializingAgents[agentType]) return;
    this.initializingAgents[agentType] = true;
    this.cdr.markForCheck();
    try {
      this.agents[agentType] = await this.gateway.addAgent(agentType);

      this.cdr.markForCheck();
    } catch (e) {
      console.error(`Init Agent ${agentType} failed:`, e);
    } finally {
      this.initializingAgents[agentType] = false;
      this.cdr.markForCheck();
    }
    console.timeEnd('initialize agent');
  }

  get canSend(): boolean {
    return (
      this.runCachedMessages ||
      (!!this.agents[this.currentAgent!.agentType] && Object.keys(this.agents).length > 0)
    );
  }

  get isAnyAgentWorking(): boolean {
    return this.workingGuids.size > 0;
  }

  displayText(m: ChatMessage): string {
    if (m.msgType === 'tool_end' && m.text) {
      try {
        const parsed = JSON.parse(m.text);
        return parsed?.result?.message || parsed?.message || m.toolName || 'Done';
      } catch {
        /* fall through */
      }
    }

    return m.text;
  }

  getRouteCard(text: string): RouteCard | null {
    if (!text.startsWith('__ROUTE_CARD__')) return null;
    const id = text.slice('__ROUTE_CARD__'.length);
    return this.routeCards.get(id) ?? null;
  }

  formatDistance(mi: number): string {
    return `${mi.toFixed(2)} mi`;
  }

  trackById(_: number, p: PathEntry): number {
    return p.id;
  }
  trackByDisplayIdx(i: number, _: DisplayItem): number {
    return i;
  }
  trackBySimRunnerId(_: number, sr: SimRunner): string {
    return sr.id;
  }

  setToolCallToWarning() {
    const toolCallToWarn = this.displayItems.find((item) => {
      if (!('msg' in item)) return false;
      return (
        item.msg.speaker.includes('simulator_with_failure') &&
        item.msg.toolName === 'prepare_simulation'
      );
    });
    if (!toolCallToWarn || toolCallToWarn.kind !== 'tool_call') return;

    toolCallToWarn.done = true;
    toolCallToWarn.warning = true;
    toolCallToWarn.msg = { ...toolCallToWarn.msg, text: this.displayText(toolCallToWarn.msg) };

    this.displayItems = [...this.displayItems];
    this.cdr.markForCheck();
  }

  // ── Display item grouping ──────────────────────────────────────────

  addDisplayItem(item: DisplayItem) {
    if (this.isSecuringAgent) return;
    this.displayItems.push(item);
  }

  finishToolCall(msg: ChatMessage) {
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
  }

  private processMessageForDisplay(msg: ChatMessage): void {
    // console.log('process', msg);
    //
    // Route cards
    // if (msg.text.startsWith('__ROUTE_CARD__')) {
    //   const card = this.getRouteCard(msg.text);
    //   if (card) {
    //     this.displayItems = [...this.displayItems, { kind: 'route', msg, card }];
    //     return;
    //   }
    // }

    // User messages and system messages — standalone
    // if (msg.guid === 'system') {
    //   this.displayItems = [...this.displayItems, { kind: 'system', msg }];
    //   return;
    // }

    if (msg.isUser) {
      this.addDisplayItem({ kind: 'message', msg });
      return;
    }

    // Messages from organizer tab
    if (msg.toolName === 'get_planned_routes_data') {
      return;
    }

    // Messages from organizer tab
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
        this.addDisplayItem({
          kind: 'system',
          msg,
        });
        return;

      case AgentMessageType.RUN_START:
        // this.addDisplayItem({
        //   kind: 'message',
        //   msg: { ...msg, text: 'Initialized and working on your task.' },
        // });

        return;

      case AgentMessageType.RUN_END:
        if (msg.guid === this.agents[this.currentAgent!.agentType]) {
          this.isAgentWorking = false;
        }

        this.isSecuringAgent = false;

        return;

      case AgentMessageType.MODEL_START:
        // Skip — don't show thinking steps
        return;

      case AgentMessageType.MODEL_END:
        if (this.finalToolCallMessage) {
          this.displayItems = [...this.displayItems, this.finalToolCallMessage];
        }

        // TODO :: this message neexs to be cleaned up by backend
        // This will be the final report card
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
      //   const modelGroup = this.activeGroups.get(msg.guid);
      //   const text = msg.text;
      //   const tokenMatch = text.match(/\((\d+) tokens\)$/);
      //   if (tokenMatch && modelGroup) modelGroup.totalTokens += parseInt(tokenMatch[1], 10);
      //   const cleanText = text.replace(/\s*\(\d+ tokens\)$/, '');
      //   if (cleanText && modelGroup) modelGroup.finalText = this.cleanJsonText(cleanText);
      //   this.displayItems = [...this.displayItems];
      //   return;

      case AgentMessageType.TOOL_START:
        if (this.filterSettings.showToolCalls && msg.toolName) {
          const idx = this.displayItems.length;
          this.addDisplayItem({
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
          this.addDisplayItem({ kind: 'a2ui', node: msg.result });
          return;
        }

        if (msg.toolName === 'set_financial_modeling_mode') {
          this.displayItems = [];

          this.chatMessages = [];
          this.expandedToolCalls.clear();
          this.activeToolCalls.clear();

          const activeDemoKey = this.demoService.activeDemo();
          const activeDemo = DEMO_CONFIG[activeDemoKey] as any;

          if (activeDemo.promptPlaceholder) {
            if (this.chatTextAreaRef) {
              this.chatTextAreaRef.nativeElement.value = activeDemo.promptPlaceholder;
            }
            this.chatInput = activeDemo.promptPlaceholder;
            if (this.chatTextAreaRef) {
              this.autoResize();
            }
          }
        }

        if (msg.toolName === 'fire_start_gun') {
          this.resetSimulationStatistics();

          this.handleRaceStarted();
        }

        if (msg.toolName === 'advance_tick') {
          this.handleTickUpdate(msg.result);
          return;
        }

        if (this.filterSettings.showToolCalls) {
          if (
            (msg.toolName && this.activeToolCalls.has(msg.toolName)) ||
            (msg.toolName === 'load_skill' && this.activeToolCalls.has(msg.skillName!))
          )
            this.finishToolCall(msg);
          // todo :: show tool start vs end
          return;
        }

        return;
      case AgentMessageType.TOOL_ERROR:
        if (this.filterSettings.showToolCalls) {
          if (msg.speaker.includes(demoFiveSpeaker)) {
            const idx = this.activeToolCalls.get('prepare_simulation');
            if (idx === undefined) return;
            const item = this.displayItems[idx];
            if (!item || item.kind !== 'tool_call') return;

            if (this.demoService.activeDemo() === '5a') {
              setTimeout(this.setToolCallToWarning.bind(this), 1000);

              return;
            }

            item.done = true;
            item.error = true;
            item.msg = { ...item.msg, text: this.displayText(msg) };
            this.activeToolCalls.delete('prepare_simulation');
            this.displayItems = [...this.displayItems];
          }
        }

        this.isAgentWorking = false;

        // Always emit the error as its own standalone message bubble
        this.addDisplayItem({ kind: 'message', msg });

        if (msg.speaker.toLowerCase().includes('simulator_with_failure')) {
          if (this.demoService.activeDemo() === '5a') {
            return;
          }

          let count = 0;

          this.errorMessageInterval = setInterval(() => {
            if (count >= 15) {
              clearInterval(this.errorMessageInterval as number);
            }

            if (count === 3) {
              window.dispatchEvent(new CustomEvent('sim:reset'));
              window.dispatchEvent(new CustomEvent('sim:triggerError'));
            }

            this.addDisplayItem({ kind: 'message', msg });
            this.cdr.markForCheck();
            setTimeout(() => this.scrollChatToBottom(), 0);
            count++;
          }, 1000);
        }

        return;

      case AgentMessageType.INTER_AGENT:
        // text: "📢 planner_with_eval -> simulator:
        // const split = msg.text.split(' ');

        // const message =
        //   split[2] === '->'
        //     ? `${split[1]} agent communicating with ${split[3].replace(/[^a-zA-Z0-9 ]/g, '')} agent`
        //     : `${split[3].replace(/[^a-zA-Z0-9 ]/g, '')} agent communicating with ${split[1]} agent`;

        this.addDisplayItem({
          kind: 'message',
          msg,
        });
        return;
      case AgentMessageType.TEXT:
        this.addDisplayItem({
          msg,
          kind: 'message',
        });

        return;
      case AgentMessageType.AGENT_START:
        return;
      case AgentMessageType.AGENT_END:
        return;
      case AgentMessageType.INTER_AGENT:
        this.displayItems = [...this.displayItems, { kind: 'message', msg }];
        return;
      case AgentMessageType.MODEL_ERROR:
        this.displayItems = [...this.displayItems, { kind: 'message', msg }];
        if (msg.guid === this.agents[this.currentAgent!.agentType]) {
          this.isAgentWorking = false;
        }
        return;
      default:
        console.warn('Message Type not implemented:', msg.msgType);
    }
  }

  /** Filter display items based on active tab */
  // get filteredDisplayItems(): DisplayItem[] {
  //   return this.displayItems.filter((item) => {
  //     // tick_progress items are simulation-wide and always shown regardless of agent filter
  //     if (item.kind === 'tick_progress') return true;

  //     const guid = item.kind === 'activity' ? item.group.guid : item.msg.guid;

  //     return guid === this.agents[this.currentAgent] || guid === 'system';
  //   });
  // }

  resetSimulationStatistics(): void {
    this.simulationProgress = 0;
    this.averageDistance = 0;
    this.numberOfFinishers = 0;
    this.runnersFinishedAwaitingHud.clear();
    this.runnerCourseProgressByGuid.clear();
    this.runnersFinished.clear();
    this.averagePace = '0:00';

    if (this.simProgressRafId) {
      cancelAnimationFrame(this.simProgressRafId);
      this.simProgressRafId = null;
    }
  }

  // ── Simulation dashboard helpers ─────────────────────────────────

  get latestSnapshot(): SimulationSnapshot | null {
    const snaps = this.simState.snapshots;
    return snaps.length > 0 ? snaps[snaps.length - 1] : null;
  }

  get statusEntries(): { key: string; value: number }[] {
    if (!this.latestSnapshot) return [];
    return Object.entries(this.latestSnapshot.statusCounts).map(([key, value]) => ({
      key,
      value,
    }));
  }

  get hrSparkline(): string {
    return this.buildSparkline(this.simState.snapshots.map((s) => s.avgVelocity));
  }

  get paceSparkline(): string {
    return this.buildSparkline(this.simState.snapshots.map((s) => s.avgVelocity));
  }

  get hydrationSparkline(): string {
    return this.buildSparkline(this.simState.snapshots.map((s) => s.avgWater));
  }

  private buildSparkline(values: number[]): string {
    if (values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    return values
      .map((v, i) => {
        const x = (i / (values.length - 1)) * 100;
        const y = 30 - ((v - min) / range) * 28;
        return `${x},${y}`;
      })
      .join(' ');
  }

  formatRaceTime(minutes: number): string {
    const h = Math.floor(minutes / 60);
    const m = Math.floor(minutes % 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  objectEntries(obj: Record<string, unknown>): [string, unknown][] {
    return Object.entries(obj);
  }
}
