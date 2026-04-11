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
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  ViewChild,
  ElementRef,
  effect,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { GatewayService, ChatMessage } from '../../../../gateway.service';
import { DemoService } from '../../../DemoOverlay/demo.service';
import { DEMO_CONFIG } from '../../../../demo-config';

@Component({
  selector: 'app-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  styleUrls: ['./Log.scss'],
  template: `
    <div class="panel">
      <div class="agent-communication" [hidden]="speakersArray.length <= 1">
        <ng-container *ngFor="let speaker of speakersArray; let last = last">
          <div class="agent-wrapper">
            <div class="agent">{{ speaker }}</div>
            <div class="dot"></div>
          </div>
          <div *ngIf="!last" class="communication">
            <div class="indicator"></div>
          </div>
        </ng-container>
      </div>
      <div class="log-header" *ngIf="messages.length > 0">
        <p class="label time">TIME</p>
        <p class="label agent">AGENT</p>
        <p class="label type">TYPE</p>
        <p class="label message">MESSAGE</p>
      </div>

      <div class="log-scroll" #logScroll (scroll)="onScroll()">
        <div
          *ngFor="let msg of messages; trackBy: trackByMsg"
          class="log-entry"
          [class.is-start]="isStart(msg.msgType)"
          [class.is-end]="isEnd(msg.msgType)"
          [class.is-error]="isError(msg.msgType)"
          [class.is-tool]="isTool(msg.msgType)"
          [class.is-model]="isModel(msg.msgType)"
          [class.expanded]="expandedMsgs.has(msg)"
        >
          <div class="indicator" [ngClass]="typeClass(msg)"></div>
          <div class="log-row" [ngClass]="typeClass(msg)" (click)="toggleExpand(msg)">
            <div class="log-time">{{ msg.timestamp | date: 'hh:mm:ss a' }}</div>
            <div class="log-agent">
              {{ getSpeakerDisplayName(msg.speaker) }}
            </div>
            <div class="log-type-wrapper">
              <div class="log-type">
                {{ getDisplayType(msg.msgType) }}
              </div>
            </div>
            <div class="log-summary" [innerHTML]="summary(msg)"></div>
          </div>
          <div class="log-details-wrapper" [class.open]="expandedMsgs.has(msg)">
            <div class="log-details" (click)="$event.stopPropagation()">
              <pre>{{ msg.rawJson }}</pre>
            </div>
          </div>
        </div>
      </div>
      <div class="log-top-gradient"></div>

      <button *ngIf="!atTop" class="btn-scroll-top" (click)="scrollToTop()" title="Jump to latest">
        <span class="material-icons" style="font-size:16px">keyboard_arrow_up</span>
      </button>
    </div>
  `,
})
export class LogComponent implements OnInit, OnDestroy {
  @ViewChild('logScroll') logScrollRef!: ElementRef<HTMLDivElement>;

  messages: ChatMessage[] = [];
  expandedMsgs = new Set<ChatMessage>();
  atTop = true;

  private sub!: Subscription;

  private demoService = inject(DemoService);
  private resetCounter = 0;

  private dict = {
    tool_start: 'TOOL',
    tool_end: 'TOOL',
    tool_error: 'TOOL',
    run_start: 'RUN',
    run_end: 'RUN',
    text: 'TEXT',
  };
  private speakers = new Set<string>();

  private speakerDict = {
    planner: 'PLANNER',
    planner_with_eval: 'PLANNER',
    planner_with_memory: 'PLANNER',
    simulator_with_failure: 'PLANNER',
    simulator: 'SIMULATOR',
    tick: 'runner',
    simulation_pipeline: 'runner',
  };

  get speakersArray(): string[] {
    return Array.from(this.speakers);
  }

  constructor(
    private gateway: GatewayService,
    private cdr: ChangeDetectorRef,
  ) {
    effect(async () => {
      // to generate reset
      this.resetCounter = this.demoService.reset();
      const activeDemo = DEMO_CONFIG[this.demoService.activeDemo()] as any;
      this.messages = [];
      this.cdr.markForCheck();
    });
  }

  getDisplayType(type: string) {
    return this.dict[type as keyof typeof this.dict] || `${type}`;
  }

  getSpeakerDisplayName(speaker: string) {
    const trimmedSpeaker = speaker.split(' ')[0];
    if (!this.speakerDict[trimmedSpeaker as keyof typeof this.speakerDict]) {
      // console.log('MISSING IS ', trimmedSpeaker);
    }
    return this.speakerDict[trimmedSpeaker as keyof typeof this.speakerDict] || 'AGENT';
  }

  ngOnInit(): void {
    this.sub = this.gateway.chat$.subscribe((msg: ChatMessage) => {
      if (msg.msgType === 'tool_end' && msg.toolName === 'stop_race_collector') {
        this.speakers.delete(this.getSpeakerDisplayName('tick'));
        // console.log('remove speaker', msg);
      }

      if (
        msg.speaker === 'You' ||
        // msg.speaker.includes('simulation_pipeline') ||
        msg.speaker.includes('pre_race') ||
        msg.speaker.includes('post_race') ||
        msg.speaker.includes('system') ||
        msg.msgType === 'inter_agent'
      ) {
        // console.log('hide', msg);
        return;
      }

      this.speakers.add(this.getSpeakerDisplayName(msg.speaker));
      // console.log('add speaker', msg);

      if (msg.msgType === 'run_end') {
        this.speakers.delete(this.getSpeakerDisplayName(msg.speaker));
        // console.log(';remove speaker', msg);
      }
      this.messages = [msg, ...this.messages];
      this.cdr.markForCheck();
      if (this.atTop) {
        setTimeout(() => this.scrollToTop(), 0);
      }
    });
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }

  onScroll(): void {
    if (!this.logScrollRef) return;
    const el = this.logScrollRef.nativeElement;
    this.atTop = el.scrollTop < 30;
    this.cdr.markForCheck();
  }

  scrollToTop(): void {
    if (this.logScrollRef) {
      const el = this.logScrollRef.nativeElement;
      el.scrollTop = 0;
    }
    this.atTop = true;
    this.cdr.markForCheck();
  }

  toggleExpand(msg: ChatMessage): void {
    if (this.expandedMsgs.has(msg)) {
      this.expandedMsgs.delete(msg);
    } else {
      this.expandedMsgs.add(msg);
    }
    this.cdr.markForCheck();
  }

  trackByMsg(_i: number, msg: ChatMessage): ChatMessage {
    return msg;
  }

  sessionColor(guid: string): string {
    return this.hashToHsl(guid, 80, 55);
  }

  agentColor(name: string): string {
    return this.hashToHsl(name || 'system', 70, 65);
  }

  private hashToHsl(str: string, saturation: number, lightness: number): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash % 360);
    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  }

  typeClass(msg: ChatMessage): string {
    if (msg.isUser) return 'type-user';
    const t = msg.msgType;
    if (t === 'tool_error') return 'error';
    if (t.includes('tool')) return 'tool';
    if (t.includes('model')) return 'type-model';
    if (t.includes('run')) return 'run';
    if (t === 'text') return 'text';
    return 'type-lifecycle';
  }

  isStart(t: string): boolean {
    return t === 'run_start' || t === 'model_start' || t === 'tool_start' || t === 'agent_start';
  }

  isEnd(t: string): boolean {
    return t === 'run_end' || t === 'model_end' || t === 'tool_end' || t === 'agent_end';
  }

  isError(t: string): boolean {
    return t.includes('error');
  }

  isTool(t: string): boolean {
    return t.includes('tool') && !t.includes('error');
  }

  isModel(t: string): boolean {
    return t.includes('model');
  }

  summary(msg: ChatMessage): string {
    if (msg.isUser) {
      return `👤 <strong>You:</strong> ${(msg.text || '').substring(0, 120)}`;
    }
    const t = msg.msgType;
    const text = msg.text || '';
    const tool = msg.toolName || '';
    const truncate = (s: string, n = 100) => s.substring(0, n) + (s.length > n ? '…' : '');

    switch (t) {
      case 'run_start':
        return '<span class="badge badge-start">START</span> 🚀 New execution';
      case 'run_end':
        return '<span class="badge badge-end">END</span> 🏁 Execution complete';
      case 'agent_start':
        return '<span class="badge badge-start">AGENT</span> ▶ Starting agent';
      case 'agent_end':
        return '<span class="badge badge-end">AGENT</span> ✔ Agent finished';
      case 'model_start':
        return '🧠 Thinking…';
      case 'model_end':
        return text ? `💬 ${truncate(text)}` : '💬 Turn complete';
      case 'tool_start':
        return `▶ Call <strong>${tool}</strong>`;
      case 'tool_end':
        return `✔ Result from <strong>${tool}</strong>`;
      case 'tool_error':
        return `❌ Tool error${tool ? ` (${tool})` : ''}: ${truncate(text, 80)}`;
      case 'text':
        return text ? `💬 ${truncate(text)}` : '';
      case 'system':
        return `⚙ ${truncate(text)}`;
      default:
        return text ? truncate(text) : t;
    }
  }
}
