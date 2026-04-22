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
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  OnDestroy,
  AfterViewInit,
  ViewChildren,
  QueryList,
  ElementRef,
} from '@angular/core';

const ROTATION_DURATION_MS = 600;
const SLIDE_DURATION_MS = 500;
const PULSE_TRIGGER_DELAY_MS = 330;
const SLIDE_PULSE_TRIGGER_DELAY_MS = 320;
const PULSE_DURATION_MS = 600;
const PULSE_FRONT_WIDTH_DEG = 35;
const PULSE_TRAIL_WIDTH_DEG = 110;
const PULSE_DECAY_EXPONENT = 1.8;
const DASH_BASE_OPACITY = 0.3;
const DASH_BOOST_OPACITY = 1.0;
const DASH_BOOST_SCALE = 2.8;

@Component({
  selector: 'app-countdown-overlay',
  standalone: true,
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['./countdown-overlay.scss'],
  template: `
    <div class="overlay" [class.entered]="entered">
      <div class="ring" [style.transform]="'rotate(' + rotationDeg + 'deg)'">
        <div class="ring-bg"></div>
        <div class="dashes">
          @for (i of dashIndices; track i) {
            <div #dashEl class="dash" [style.--dash-angle]="i * 6 + 'deg'"></div>
          }
        </div>
        @if (slotA !== null && slotA >= 0) {
          <div class="number slot-a">{{ slotA }}</div>
        }
        @if (slotB !== null && slotB >= 0) {
          <div class="number slot-b">{{ slotB }}</div>
        }
      </div>
    </div>
  `,
})
export class CountdownOverlayComponent implements OnDestroy, AfterViewInit {
  slotA: number | null = null;
  slotB: number | null = null;
  rotationDeg = 0;
  entered = false;
  showingSlot: 'A' | 'B' = 'A';

  readonly dashIndices = Array.from({ length: 60 }, (_, i) => i);

  @ViewChildren('dashEl') dashElsList!: QueryList<ElementRef<HTMLDivElement>>;
  private dashEls: HTMLDivElement[] = [];

  private hideTimer: ReturnType<typeof setTimeout> | undefined;
  private prepTimer: ReturnType<typeof setTimeout> | undefined;
  private pulseTriggerTimer: ReturnType<typeof setTimeout> | undefined;
  private rafId: number | null = null;
  private pulseStartMs: number | null = null;
  private pulseAngle = 90;

  private readonly onShow = (e: Event) => {
    const value = (e as CustomEvent<number>).detail;
    if (this.hideTimer !== undefined) {
      clearTimeout(this.hideTimer);
      this.hideTimer = undefined;
    }
    if (this.pulseTriggerTimer !== undefined) {
      clearTimeout(this.pulseTriggerTimer);
      this.pulseTriggerTimer = undefined;
    }

    if (!this.entered) {
      this.slotA = value;
      this.slotB = value - 1;
      this.showingSlot = 'A';
      this.rotationDeg = 0;
      this.entered = true;
      this.pulseTriggerTimer = setTimeout(() => {
        this.pulseTriggerTimer = undefined;
        this.startPulse(0);
      }, SLIDE_PULSE_TRIGGER_DELAY_MS);
    } else {
      this.rotationDeg += 180;
      this.showingSlot = this.showingSlot === 'A' ? 'B' : 'A';
      const newHidden: 'A' | 'B' = this.showingSlot === 'A' ? 'B' : 'A';
      const nextNext = value - 1;
      if (this.prepTimer !== undefined) clearTimeout(this.prepTimer);
      this.prepTimer = setTimeout(() => {
        this.prepTimer = undefined;
        if (newHidden === 'A') this.slotA = nextNext;
        else this.slotB = nextNext;
        this.cdr.markForCheck();
      }, ROTATION_DURATION_MS);
      const pulseRotationNew = this.rotationDeg;
      this.pulseTriggerTimer = setTimeout(() => {
        this.pulseTriggerTimer = undefined;
        this.startPulse(pulseRotationNew);
      }, PULSE_TRIGGER_DELAY_MS);
    }

    this.cdr.markForCheck();
  };

  private readonly onHide = () => {
    if (this.prepTimer !== undefined) {
      clearTimeout(this.prepTimer);
      this.prepTimer = undefined;
    }
    if (this.pulseTriggerTimer !== undefined) {
      clearTimeout(this.pulseTriggerTimer);
      this.pulseTriggerTimer = undefined;
    }
    this.entered = false;
    this.cdr.markForCheck();
    if (this.hideTimer !== undefined) clearTimeout(this.hideTimer);
    this.hideTimer = setTimeout(() => {
      this.hideTimer = undefined;
      this.slotA = null;
      this.slotB = null;
      this.rotationDeg = 0;
      this.showingSlot = 'A';
      this.cdr.markForCheck();
    }, SLIDE_DURATION_MS);
  };

  constructor(private cdr: ChangeDetectorRef) {
    window.addEventListener('countdown:show', this.onShow);
    window.addEventListener('countdown:hide', this.onHide);
  }

  ngAfterViewInit(): void {
    this.dashEls = this.dashElsList.toArray().map((r) => r.nativeElement);
    this.dashElsList.changes.subscribe(() => {
      this.dashEls = this.dashElsList.toArray().map((r) => r.nativeElement);
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('countdown:show', this.onShow);
    window.removeEventListener('countdown:hide', this.onHide);
    if (this.hideTimer !== undefined) clearTimeout(this.hideTimer);
    if (this.prepTimer !== undefined) clearTimeout(this.prepTimer);
    if (this.pulseTriggerTimer !== undefined) clearTimeout(this.pulseTriggerTimer);
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
  }

  private startPulse(rotationAtTriggerDeg: number): void {
    this.pulseStartMs = performance.now();
    this.pulseAngle = (((90 - rotationAtTriggerDeg) % 360) + 360) % 360;
    if (this.rafId === null) {
      this.rafId = requestAnimationFrame(this.tick);
    }
  }

  private tick = (now: number): void => {
    this.rafId = null;
    if (this.pulseStartMs === null) return;

    const elapsed = now - this.pulseStartMs;
    const t = elapsed / PULSE_DURATION_MS;

    if (t >= 1) {
      for (const el of this.dashEls) {
        el.style.removeProperty('--dash-scale');
        el.style.removeProperty('--dash-opacity');
      }
      this.pulseStartMs = null;
      return;
    }

    const wavePos = t * 180;
    const timeFalloff = Math.pow(1 - t, PULSE_DECAY_EXPONENT);

    for (let i = 0; i < this.dashEls.length; i++) {
      const dashAngle = i * 6;
      let dist = Math.abs(dashAngle - this.pulseAngle);
      if (dist > 180) dist = 360 - dist;

      const signed = dist - wavePos;
      let spatialEnv = 0;
      if (signed >= 0 && signed < PULSE_FRONT_WIDTH_DEG) {
        const x = signed / PULSE_FRONT_WIDTH_DEG;
        spatialEnv = (1 + Math.cos(x * Math.PI)) / 2;
      } else if (signed < 0 && -signed < PULSE_TRAIL_WIDTH_DEG) {
        const x = -signed / PULSE_TRAIL_WIDTH_DEG;
        spatialEnv = (1 + Math.cos(x * Math.PI)) / 2;
      }

      if (spatialEnv > 0) {
        const env = spatialEnv * timeFalloff;
        const scale = 1 + env * (DASH_BOOST_SCALE - 1);
        const opacity =
          DASH_BASE_OPACITY + env * (DASH_BOOST_OPACITY - DASH_BASE_OPACITY);
        this.dashEls[i].style.setProperty('--dash-scale', scale.toString());
        this.dashEls[i].style.setProperty('--dash-opacity', opacity.toString());
      } else {
        this.dashEls[i].style.removeProperty('--dash-scale');
        this.dashEls[i].style.removeProperty('--dash-opacity');
      }
    }

    this.rafId = requestAnimationFrame(this.tick);
  };
}
