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

import { Component, effect, inject, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-score-card',
  standalone: true,
  imports: [CommonModule],
  styleUrls: ['./ScoreCard.scss'],
  template: `
    <div class="scorecard" [class.simulation]="!this.plan" [class.current]="this.current">
      <div class="preview">
        <div class="information">
          <div class="top-row">
            <span class="type">{{ type }}</span>
            <span>{{ version }}</span>
            <span>{{ date }}</span>
            <span>{{ timestamp }}</span>
          </div>
          <h2>{{ title }}</h2>
        </div>
        <div class="score">
          <span class="value">75</span>
          <span class="label">Score</span>
        </div>
      </div>
      <div class="actions-container">
        <button (click)="onShowScoreCard()">
          <span class="material-icons unfold">unfold_more</span>

          <p>Show score card</p>
        </button>
        <ng-container *ngIf="!this.plan; else play">
          <button (click)="onRunSimulation($event)">
            <span class="material-icons">play_arrow</span>
            <p>Run simulation</p>
          </button>
        </ng-container>
        <ng-template #play>
          <button (click)="onShowRoute()">
            <span class="material-icons">arrow_forward</span>
            <p>Show route</p>
          </button>
        </ng-template>
      </div>
    </div>
  `,
})
export class ScoreCardComponent implements OnInit {
  @Input() route: any;
  protected isOpen = false;

  protected timestamp = '14:38:11 AM';
  protected date = '25/03/26';
  protected version = '#1234';
  protected type: 'PLAN' | 'SIMULATED' = 'PLAN';
  protected title = 'EL CLASSICO';

  protected current = false;
  protected plan = false;

  constructor() {}

  ngOnInit(): void {
    this.title = this.route.name;
    this.current = false;
    this.plan = true;
  }

  onShowScoreCard(): void {}

  onRunSimulation(e: any): void {
    e.stopPropagation();
    // const newPlannerAgent = await this.gateway.addAgent('planner_with_memory');

    // this.gateway.sendBroadcast(`Run Simulation for ${name}`, [newPlannerAgent]);
  }
  onShowRoute(): void {
    window.dispatchEvent(
      new CustomEvent('gateway:routeGeojson', { detail: { geojson: this.route.route_data } }),
    );
  }

  onHistoryClick(): void {}
}
