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

import { Component, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';

interface FilterItem {
  id: string;
  icon: string;
  active: boolean;
  alwaysActive?: boolean;
  options: string[];
  optionIndex: number;
  prevLabel: string;
  animating: boolean;
}

@Component({
  selector: 'app-filter-menu',
  standalone: true,
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['./filter-menu.scss'],
  template: `
    <div class="filter-menu" [class.open]="open">
      <button
        class="toggle-btn"
        (click)="open = !open"
        aria-label="Toggle filter menu"
      >
        <span class="material-icons">{{ open ? 'unfold_less' : 'unfold_more' }}</span>
      </button>

      @for (item of filters; track item.id) {
        <div class="filter-row">
          <button
            class="filter-item"
            [class.active]="item.active"
            (click)="toggleFilter(item)"
          >
            <span class="material-symbols-outlined">{{ item.icon }}</span>
          </button>
          <span class="filter-label">
            <span class="label-scroll" [class.animating]="item.animating">
              <span class="label-old">{{ item.prevLabel }}</span>
              <span class="label-current">{{ item.options[item.optionIndex] }}</span>
            </span>
          </span>
        </div>
      }
    </div>
  `,
})
export class FilterMenuComponent {
  open = true;

  filters: FilterItem[] = [
    { id: 'entertainment', icon: 'music_note_2', active: true, options: ['Entertainment'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'sentiment', icon: 'chat', active: true, options: ['Sentiment'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'race-info', icon: 'sports_score', active: true, options: ['Race info'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'race-support', icon: 'health_and_safety', active: true, options: ['Race Support'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'camera', icon: 'videocam', active: true, alwaysActive: true, options: ['Camera A', 'Camera B', 'Camera C'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'panning', icon: 'autoplay', active: true, options: ['Panning On', 'Panning Off'], optionIndex: 0, prevLabel: '', animating: false },
  ];

  constructor(private cdr: ChangeDetectorRef) {}

  toggleFilter(item: FilterItem): void {
    if (item.options.length > 1) {
      item.animating = false;
      this.cdr.markForCheck();

      requestAnimationFrame(() => {
        item.prevLabel = item.options[item.optionIndex];
        item.optionIndex = (item.optionIndex + 1) % item.options.length;
        if (!item.alwaysActive) {
          item.active = item.optionIndex === 0;
        }
        item.animating = true;
        this.cdr.markForCheck();

        window.dispatchEvent(
          new CustomEvent('filter:changed', {
            detail: { id: item.id, value: item.options[item.optionIndex], index: item.optionIndex },
          }),
        );

        setTimeout(() => {
          item.animating = false;
          this.cdr.markForCheck();
        }, 300);
      });
      return;
    } else {
      item.active = !item.active;
      window.dispatchEvent(
        new CustomEvent('filter:changed', {
          detail: { id: item.id, active: item.active },
        }),
      );
    }

    this.cdr.markForCheck();
  }
}
