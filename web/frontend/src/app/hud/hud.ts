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
  ElementRef,
  ChangeDetectionStrategy,
  HostListener,
} from '@angular/core';
import { DEMO_CONFIG } from '../demo-config';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DemoService } from '../components/DemoOverlay/demo.service';
import { DEMO_IDS } from '../../constants';
import { AgentScreenComponent } from '../components/ChatNavPanel/screens/AgentScreen/AgentScreen';

@Component({
  selector: 'app-hud',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, AgentScreenComponent],
  styleUrls: ['./hud.scss'],
  template: `
    <!-- ── Top-left: Hamburger menu ──────────────────────────────── -->
    <div class="menu-wrapper">
      <div class="information-wrapper">
        <button
          class="menu-button"
          (click)="hamburgerOpen = !hamburgerOpen"
          [class.hamburger-btn--open]="hamburgerOpen"
          aria-label="Menu"
        >
          <span class="material-icons">
            {{ hamburgerOpen ? 'close' : 'menu' }}
          </span>
        </button>
        <h4 class="demo-title">
          {{ DEMO_CONFIG[demoService.activeDemo()].title }}
        </h4>
      </div>
      <div class="menu" [class.isOpen]="hamburgerOpen" (click)="hamburgerOpen = false">
        <h1 class="menu-title">Browse demos</h1>
        <div class="menu-panel" (click)="$event.stopPropagation()">
          <div
            *ngFor="let id of demoIds; let i = index"
            class="menu-item"
            [class.active]="demoService.activeDemo() === id"
            (click)="demoService.select(id); hamburgerOpen = false"
          >
            <span class="demo-number">{{
              i === 6 ? '5b' : i === 8 ? '7b' : (i | number: '2.0-0')
            }}</span>
            <p class="demo-name">{{ DEMO_CONFIG[id].title }}</p>
            <span class="icon material-icons">{{
              demoService.activeDemo() === id ? 'autorenew' : 'arrow_forward'
            }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Bottom-right: Info Panel ──────────────────────────────── -->
    <div
      class="debug-race-panel"
      *ngIf="isDebugMode && pathCount > 0 && simRunnerGuids.length === 0"
      style="
      position: fixed; top: 16px; right: 16px; z-index: 100000;
      background: rgba(0,0,0,0.85); border: 1px solid rgba(255,255,255,0.15);
      border-radius: 8px; padding: 12px 16px; color: #fff; font-size: 13px;
      display: flex; gap: 8px; align-items: center; pointer-events: all;
    "
    >
      <span style="opacity: 0.6">Debug Race</span>
      <input
        type="number"
        [(ngModel)]="debugRunnerCount"
        min="1"
        max="1000"
        style="width: 48px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
        border-radius: 4px; color: #fff; padding: 4px 6px; text-align: center; font-size: 13px;"
      />
      <span style="opacity: 0.6; margin-left: 4px">Speed</span>
      <select
        [(ngModel)]="debugSimSpeed"
        style="
        background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
        border-radius: 4px; color: #fff; padding: 4px 6px; font-size: 13px; cursor: pointer;
      "
      >
        <option *ngFor="let s of debugSimSpeedOptions" [ngValue]="s">{{ s }}x</option>
      </select>
      <button
        (click)="onStartDebugRace()"
        style="
        background: #4d96ff; border: none; border-radius: 4px;
        color: #fff; padding: 4px 12px; cursor: pointer; font-size: 13px;
      "
      >
        Start
      </button>
    </div>

    <agent-screen></agent-screen>

    @if (demoService.modeSwitchLabel(); as modeLabel) {
      <div class="mode-switch-label">{{ modeLabel }}</div>
    }

    <!-- ── Bottom-right: Debug Panel ──────────────────────────────── -->
    <div
      class="debug-tools-panel"
      *ngIf="isDebugMode"
      style="
      position: fixed; bottom: 16px; left: 16px; z-index: 100000;
      background: rgba(0,0,0,0.85); border: 1px solid rgba(255,255,255,0.15);
      border-radius: 8px; padding: 8px 12px; color: #fff; font-size: 13px;
      display: flex; gap: 8px; align-items: center; pointer-events: all;
    "
    >
      <button
        (click)="onCopyLog()"
        style="
        background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
        border-radius: 4px; color: #fff; padding: 4px 12px; cursor: pointer; font-size: 13px;
      "
      >
        {{ copyLogLabel }}
      </button>
    </div>
  `,
})
export class HudComponent implements OnInit, OnDestroy {
  readonly DEMO_CONFIG = DEMO_CONFIG;
  readonly demoIds = DEMO_IDS;

  hamburgerOpen = false;

  /** Paths in scene (from viewport sync); only length is used for debug UI. */
  pathCount = 0;

  debugRunnerCount = 10;
  debugSimSpeed = 1;
  debugSimSpeedOptions = [0.5, 1, 2, 3, 5, 10];
  copyLogLabel = 'Copy log';
  isDebugMode = new URLSearchParams(window.location.search).get('debug') === 'true';

  /** Runner guids from `hud:addSimRunner` (for debug panel visibility + `sim:reset` cleanup). */
  simRunnerGuids: string[] = [];

  constructor(
    private ngZone: NgZone,
    private cdr: ChangeDetectorRef,
    readonly demoService: DemoService,
    private el: ElementRef,
  ) {}

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.hamburgerOpen) return;
    const wrap = this.el.nativeElement.querySelector('.menu-wrapper');
    if (wrap && !wrap.contains(event.target as Node)) {
      this.hamburgerOpen = false;
      this.cdr.markForCheck();
    }
  }

  ngOnInit(): void {
    window.addEventListener('hud:sync', this.onSync);
    window.addEventListener('hud:addSimRunner', this.onNewSimRunner);
    window.addEventListener('sim:reset', this.onSimReset);
    window.addEventListener('sim:finished', this.onSimFinished);
    window.addEventListener('sim:complete', this.onSimFinished);
  }

  ngOnDestroy(): void {
    window.removeEventListener('hud:sync', this.onSync);
    window.removeEventListener('hud:addSimRunner', this.onNewSimRunner);
    window.removeEventListener('sim:reset', this.onSimReset);
    window.removeEventListener('sim:finished', this.onSimFinished);
    window.removeEventListener('sim:complete', this.onSimFinished);
  }

  private onSync = (e: Event): void => {
    const d = (e as CustomEvent).detail as { paths: unknown[] };
    this.ngZone.run(() => {
      this.pathCount = d.paths?.length ?? 0;
      this.cdr.markForCheck();
    });
  };

  private onNewSimRunner = (e: Event): void => {
    const d = (e as CustomEvent).detail as { guid: string };
    if (!d.guid || this.simRunnerGuids.includes(d.guid)) return;
    this.simRunnerGuids.push(d.guid);
    this.ngZone.run(() => this.cdr.markForCheck());
  };

  onStartDebugRace(): void {
    import('../debug-race').then((m) =>
      m.startDebugRace(this.debugRunnerCount, this.debugSimSpeed),
    );
  }

  onCopyLog(): void {
    import('../sim-logger').then((m) => {
      m.simLog.copyToClipboard().then(() => {
        this.copyLogLabel = 'Copied!';
        this.cdr.markForCheck();
        setTimeout(() => {
          this.copyLogLabel = 'Copy log';
          this.cdr.markForCheck();
        }, 2000);
      });
    });
  }

  private clearSimRunners(): void {
    for (const guid of this.simRunnerGuids) {
      window.dispatchEvent(new CustomEvent('hud:removeSimRunner', { detail: { guid } }));
    }
    this.simRunnerGuids = [];
  }

  private onSimFinished = (): void => {
    this.simRunnerGuids = [];
    this.ngZone.run(() => this.cdr.markForCheck());
  };

  private onSimReset = (): void => {
    this.clearSimRunners();
    import('../debug-race').then((m) => m.stopDebugRace());
  };
}
