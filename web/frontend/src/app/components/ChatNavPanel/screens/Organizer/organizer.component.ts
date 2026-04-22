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
  effect,
  inject,
  input,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { GatewayService, ChatMessage } from '../../../../gateway.service';
import { DEMO_CONFIG, PRECONFIGURED_ROUTES } from '../../../../demo-config';
import { DemoService } from '../../../DemoOverlay/demo.service';
import { A2uiControllerComponent } from '../../../a2ui/a2-ui-controller.component';
import { CACHED_ORGANIZER_MESSAGE } from '../../../../../constants';

@Component({
  selector: 'app-organizer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, A2uiControllerComponent],
  styleUrls: ['./Organizer.scss'],
  template: `
    <div class="panel" [class.organizer-panel--loading]="isOrganizerAgentGettingRoutes">
      <div class="wave-blur"><div class="wave-inner"></div></div>
      <ng-container *ngIf="this.isOrganizerAvailable; else noOrganizer">
        <a2ui-controller
          [runCached]="runCachedMessages()"
          [plannerAgentGuid]="plannerAgentGuid"
          *ngIf="responseNode"
          [node]="responseNode"
        ></a2ui-controller>
      </ng-container>
      <ng-template #noOrganizer>
        <div class="no-organizer-container">
          <h2>Agent has no memory context..</h2>
          <p>See agents with memory from Demo 3 onwards.</p>
        </div>
      </ng-template>
    </div>
  `,
})
export class OrganizerComponent implements OnDestroy {
  /** Bound from AgentScreen: when true, show static cached organizer surface instead of waiting on live gateway. */
  runCachedMessages = input(false);

  openItems = new Set<number>();
  preconfiguredRoutes = Object.values(PRECONFIGURED_ROUTES) as any;
  isOrganizerAvailable: boolean = false;

  responseNode: any = null;

  private demoService = inject(DemoService);
  private gateway = inject(GatewayService);
  private cdr = inject(ChangeDetectorRef);
  protected plannerAgentGuid: string | null = null;
  private chatSub: Subscription | null = null;

  protected isOrganizerAgentGettingRoutes = false;

  constructor() {
    this.chatSub = this.gateway.chat$.subscribe((msg: ChatMessage) => {
      if (msg.guid === this.plannerAgentGuid && msg.result && msg.result.surfaceUpdate) {
        this.responseNode = msg.result;
        this.isOrganizerAgentGettingRoutes = false;
        this.cdr.markForCheck();
      }
    });

    effect(async () => {
      const activeDemoKey = this.demoService.activeDemo();
      const activeDemo = DEMO_CONFIG[activeDemoKey] as any;
      this.isOrganizerAvailable =
        activeDemo.agent === 'planner_with_memory' || activeDemo.agent === 'simulator_with_failure';

      if (this.runCachedMessages()) {
        this.responseNode = CACHED_ORGANIZER_MESSAGE.data;
        this.isOrganizerAgentGettingRoutes = false;
      } else {
        this.responseNode = null;
        this.isOrganizerAgentGettingRoutes = true;
        const newPlannerAgent = await this.gateway.addAgent('planner_with_memory');
        this.plannerAgentGuid = newPlannerAgent;
        this.gateway.sendBroadcast(`list the top 3 best routes`, [newPlannerAgent], true, true);
      }
      this.cdr.markForCheck();
    });
  }

  ngOnDestroy(): void {
    this.chatSub?.unsubscribe();
  }

  toggle(index: number): void {
    if (this.openItems.has(index)) {
      this.openItems.delete(index);
    } else {
      this.openItems.add(index);
    }
  }

  onOrganizerClick(): void {}

  logStripClassic(e: any, route: any): void {
    window.dispatchEvent(
      new CustomEvent('gateway:routeGeojson', { detail: { geojson: route.route_data } }),
    );
  }

  async runSimulation(e: any, name: string): Promise<void> {
    e.stopPropagation();
    const newPlannerAgent = await this.gateway.addAgent('planner_with_memory');

    this.gateway.sendBroadcast(`Run Simulation for ${name}`, [newPlannerAgent]);
  }
}
