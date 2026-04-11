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

import { Component, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { ViewportComponent } from './viewport/viewport-lookdev';
import { HudComponent } from './hud/hud';
import { LabelComponent, LabelEntry } from './label/label';
import { FilterMenuComponent } from './components/FilterMenu/FilterMenu';
import { CountdownOverlayComponent } from './components/CountdownOverlay/CountdownOverlay';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    ViewportComponent,
    HudComponent,
    LabelComponent,
    FilterMenuComponent,
    CountdownOverlayComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-viewport-lookdev></app-viewport-lookdev>
    <app-hud></app-hud>
    <app-filter-menu></app-filter-menu>
    <app-countdown-overlay></app-countdown-overlay>
    <app-label [labels]="labels"></app-label>
  `,
  styles: [
    `
      :host {
        display: block;
        width: 100vw;
        height: 100vh;
        overflow: hidden;
      }
    `,
  ],
})
export class AppComponent {
  labels: LabelEntry[] = [];

  constructor(private cdr: ChangeDetectorRef) {
    window.addEventListener('labels:update', (e: Event) => {
      this.labels = (e as CustomEvent).detail;
      this.cdr.markForCheck();
    });
  }
}
