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
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { CountUpDirective } from 'ngx-countup';
import {
  HARDCODED_SIM_MAX_TICKS,
  HARDCODED_SIM_TICK_INTERVAL_SEC,
  HARDCODED_SIM_TOTAL_RACE_HOURS,
} from '../../../../../runner-sim-constants';

@Component({
  selector: 'simulation-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, CountUpDirective],
  styleUrls: ['./simulation-panel.scss'],
  template: `
    <div class="sim-panel-wrapper">
      <div class="simulation-running-panel">
        <div class="top-bar">
          <h1>Simulation progress</h1>
          <button class="expand-btn sim" (click)="expand.emit()">
            <span class="material-icons">unfold_more</span>
          </button>
        </div>
        <div class="progress-container" [style.--progress]="simulationProgress">
          <p class="time">
            <span class="time-part">
              <span class="time-num" [countUp]="hours"></span>
              <span class="time-unit">{{ hoursUnit }}</span></span
            >
            <span class="time-part">
              @for (hourKey of [hours]; track hourKey) {
                <span class="time-num" [countUp]="mins"></span>
              }
              <span class="time-unit">mins</span></span
            >
          </p>
        </div>

        <div class="distance">
          <div class="stat">
            <p class="value">{{ averageDistance | number : '1.1-1' }}</p>
            <p class="label">AVG. DISTANCE <span>(miles)</span></p>
          </div>
        </div>
        <div class="statistics">
          <div class="stat">
            <p class="value" [countUp]="numberOfFinishers"></p>
            <p class="label">RACE FINISHERS</p>
          </div>
          <div class="stat">
            <p class="value">{{ averagePace }}</p>
            <p class="label">AVG. PACE <span>(min/mile)</span></p>
          </div>
        </div>
        <div class="button-container">
          <button [disabled]="isFollowingLeader" (click)="followLeader.emit()" class="followButton">
            Follow the leader
          </button>
          <button class="followButton" (click)="followRandomRunner.emit()">
            I'm feeling lucky
          </button>
        </div>
      </div>
    </div>
  `,
})
export class SimulationPanelComponent {
  @Input() simulationProgress = 0;
  @Input() averageDistance: number | string = 0;
  @Input() numberOfFinishers = 0;
  @Input() averagePace = '0:00';
  @Input() isFollowingLeader = false;

  @Output() followLeader = new EventEmitter<void>();
  @Output() followRandomRunner = new EventEmitter<void>();
  @Output() expand = new EventEmitter<void>();

  private getSimulationElapsedTimeParts(): { hours: number; mins: number } {
    const wallSec = HARDCODED_SIM_MAX_TICKS * HARDCODED_SIM_TICK_INTERVAL_SEC;
    const elapsedWallSec = (this.simulationProgress / 100) * wallSec;
    const total = Math.max(
      0,
      Math.floor((elapsedWallSec / wallSec) * HARDCODED_SIM_TOTAL_RACE_HOURS * 60),
    );
    return {
      hours: Math.floor(total / 60),
      mins: total % 60,
    };
  }

  get hours(): number {
    return this.getSimulationElapsedTimeParts().hours;
  }

  get mins(): number {
    return this.getSimulationElapsedTimeParts().mins;
  }

  get hoursUnit(): string {
    return this.hours === 1 ? 'hr' : 'hrs';
  }

  get simulationRealTimeLabel(): string {
    const { hours, mins } = this.getSimulationElapsedTimeParts();
    return `${hours} hours ${mins} minutes`;
  }
}
