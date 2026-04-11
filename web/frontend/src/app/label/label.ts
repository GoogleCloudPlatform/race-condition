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
import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface LabelEntry {
  id: number;
  x: number;
  y: number;
  progress: number;
  selected: boolean;
  hovered: boolean;
  visible: boolean;
  status: 'Moving' | 'Paused';
  name?: string; // set for landmark labels; omitted for runner labels
}

@Component({
  selector: 'app-label',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div
      *ngFor="let label of labels"
      class="label"
      [class.selected]="label.selected"
      [class.hovered]="label.hovered"
      [class.show]="label.visible"
      [class.landmark]="!!label.name"
      [style.left.px]="label.x"
      [style.top.px]="label.y"
      (click)="onLabelClick(label.id)">
      <ng-container *ngIf="label.name; else runnerTpl">
        <span class="lm-pip"></span>
        <span class="lm-name">{{ label.name }}</span>
      </ng-container>
      <ng-template #runnerTpl>
        <span class="r-name">Runner {{ label.id }}</span>
        <span class="r-prog">{{ label.progress.toFixed(1) }}%</span>
      </ng-template>
    </div>
  `,
  styles: [`
    /* ── Base label (runner) ─────────────────────────────────────── */
    .label {
      position: fixed;
      transform: translate(-50%, -100%);
      display: flex;
      align-items: center;
      gap: 6px;
      background: linear-gradient(
        160deg,
        rgba(255,255,255,0.08) 0%,
        rgba(255,255,255,0.03) 55%,
        rgba(0,0,0,0.22) 100%
      );
      backdrop-filter: blur(16px) saturate(1.5);
      -webkit-backdrop-filter: blur(16px) saturate(1.5);
      border: 1px solid rgba(255,255,255,0.13);
      border-top-color: rgba(255,255,255,0.24);
      border-radius: 9px;
      padding: 5px 11px;
      font-family: 'SF Mono', 'Fira Code', monospace;
      font-size: 11px;
      white-space: nowrap;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.18s ease;
      box-shadow:
        0 6px 24px rgba(0,0,0,0.5),
        inset 0 1px 0 rgba(255,255,255,0.1),
        inset 0 -1px 0 rgba(0,0,0,0.15);
    }
    .label.show { opacity: 1; pointer-events: auto; }
    .label.selected {
      border-color: rgba(80,210,130,0.5);
      border-top-color: rgba(100,240,150,0.7);
      box-shadow:
        0 6px 24px rgba(0,0,0,0.55),
        0 0 14px rgba(80,210,130,0.22),
        inset 0 1px 0 rgba(255,255,255,0.12);
    }
    .label.hovered {
      border-color: rgba(255,255,255,0.25);
      border-top-color: rgba(255,255,255,0.38);
    }

    /* ── Landmark chip ─────────────────────────────────────────────── */
    .label.landmark {
      transform: translate(-50%, calc(-100% - 22px));
      background: linear-gradient(
        145deg,
        rgba(255,255,255,0.10) 0%,
        rgba(255,255,255,0.04) 45%,
        rgba(0,0,0,0.28) 100%
      );
      border-radius: 10px;
      padding: 5px 12px 5px 9px;
      gap: 7px;
      font-family: -apple-system, BlinkMacSystemFont, 'DM Sans', sans-serif;
      pointer-events: none;
      box-shadow:
        0 6px 28px rgba(0,0,0,0.55),
        inset 0 1px 0 rgba(255,255,255,0.12),
        inset 0 -1px 0 rgba(0,0,0,0.18);
    }
    .label.landmark.show { pointer-events: none; }

    .lm-pip {
      width: 5px; height: 5px;
      border-radius: 50%;
      flex-shrink: 0;
      background: radial-gradient(circle at 35% 35%, #fff 0%, rgba(200,220,255,0.6) 100%);
      box-shadow: 0 0 6px rgba(180,210,255,0.7);
    }
    .lm-name {
      color: rgba(255,255,255,0.93);
      font-size: 11.5px;
      font-weight: 600;
      letter-spacing: 0.01em;
      text-shadow: 0 1px 5px rgba(0,0,0,0.65);
    }
    .r-name { color: rgba(255,255,255,0.65); }
    .r-prog { color: rgba(255,255,255,0.3); font-size: 10px; }
  `]
})
export class LabelComponent {
  @Input() labels: LabelEntry[] = [];
  onLabelClick(id: number) {
    window.dispatchEvent(new CustomEvent('runner:select', { detail: { id } }));
  }
}
