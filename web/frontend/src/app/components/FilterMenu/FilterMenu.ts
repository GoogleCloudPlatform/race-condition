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

import { Component, ChangeDetectionStrategy, ChangeDetectorRef, OnInit } from '@angular/core';

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

const STORAGE_KEY = 'filter-menu-state';

@Component({
  selector: 'app-filter-menu',
  standalone: true,
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['./filter-menu.scss'],
  template: `
    <div class="filter-menu" [class.open]="open">
      @for (item of filters; track item.id) {
        @if (item.id === 'camera') {
          <div class="filter-row filter-row--camera">
            <button class="filter-item active">
              <span class="material-symbols-outlined">{{ item.icon }}</span>
            </button>
            <div class="camera-subnav">
              <div class="camera-blocker"></div>
              @for (option of item.options; track option; let i = $index) {
                <button
                  class="camera-option"
                  [class.selected]="item.optionIndex === i"
                  (click)="selectCamera(item, i)"
                >
                  <span class="material-symbols-outlined">videocam</span>
                  <span class="camera-option-letter">{{ option.slice(-1) }}</span>
                </button>
              }
            </div>
          </div>
        } @else {
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
      }

      <button
        class="toggle-btn"
        (click)="open = !open"
        aria-label="Toggle filter menu"
      >
        <span class="material-icons">{{ open ? 'unfold_less' : 'unfold_more' }}</span>
      </button>
    </div>
  `,
})
export class FilterMenuComponent implements OnInit {
  open = true;

  filters: FilterItem[] = [
    { id: 'entertainment', icon: 'music_note_2', active: true, options: ['Entertainment'], optionIndex: 0, prevLabel: '', animating: false },
    // { id: 'sentiment', icon: 'chat', active: true, options: ['Sentiment'], optionIndex: 0, prevLabel: '', animating: false },
    // { id: 'race-info', icon: 'sports_score', active: true, options: ['Race info'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'race-support', icon: 'health_and_safety', active: true, options: ['Race Support'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'camera', icon: 'videocam', active: true, alwaysActive: true, options: ['Camera A', 'Camera B', 'Camera C'], optionIndex: 0, prevLabel: '', animating: false },
    { id: 'panning', icon: 'autoplay', active: true, options: ['Orbit On', 'Orbit Off'], optionIndex: 0, prevLabel: '', animating: false },
  ];

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    this.loadState();
    for (const item of this.filters) {
      if (item.options.length > 1) {
        window.dispatchEvent(
          new CustomEvent('filter:changed', {
            detail: { id: item.id, value: item.options[item.optionIndex], index: item.optionIndex },
          }),
        );
      } else {
        window.dispatchEvent(
          new CustomEvent('filter:changed', {
            detail: { id: item.id, active: item.active },
          }),
        );
      }
    }
  }

  private saveState(): void {
    const state: Record<string, { active: boolean; optionIndex: number }> = {};
    for (const item of this.filters) {
      state[item.id] = { active: item.active, optionIndex: item.optionIndex };
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  private loadState(): void {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const state = JSON.parse(raw) as Record<string, { active: boolean; optionIndex: number }>;
      for (const item of this.filters) {
        if (item.id === 'camera') continue;
        const saved = state[item.id];
        if (!saved) continue;
        item.active = item.alwaysActive ? true : saved.active;
        item.optionIndex = Math.min(saved.optionIndex, item.options.length - 1);
      }
    } catch {
      // ignore corrupt storage
    }
  }

  selectCamera(item: FilterItem, index: number): void {
    item.optionIndex = index;
    window.dispatchEvent(
      new CustomEvent('filter:changed', {
        detail: { id: item.id, value: item.options[index], index },
      }),
    );
    this.saveState();
    this.cdr.markForCheck();
  }

  toggleFilter(item: FilterItem): void {
    if (item.id === 'camera') return;
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
        this.saveState();

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

    this.saveState();
    this.cdr.markForCheck();
  }
}
