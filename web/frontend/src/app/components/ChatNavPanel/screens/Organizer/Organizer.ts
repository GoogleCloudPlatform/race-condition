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

import { Component, effect, inject, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { GatewayService, ChatMessage } from '../../../../gateway.service';
import { DEMO_CONFIG, PRECONFIGURED_ROUTES } from '../../../../demo-config';
import { DemoService } from '../../../DemoOverlay/demo.service';
import { A2uiControllerComponent } from '../../../a2ui/a2-ui-controller';

@Component({
  selector: 'app-organizer',
  standalone: true,
  imports: [CommonModule, A2uiControllerComponent],
  styleUrls: ['./Organizer.scss'],
  template: `
    <div class="panel">
      <div class="plan-list">
        <ng-container *ngIf="this.isOrganizerAvailable; else noOrganizer">
          <div
            class="plan-item"
            [class.open]="openItems.has(i)"
            (click)="toggle(i)"
            *ngFor="let route of preconfiguredRoutes; let i = index"
          >
            <a2ui-controller [node]="organizerRouteNode(route)"></a2ui-controller>
          </div>
        </ng-container>
      </div>
      <a2ui-controller *ngIf="responseNode" [node]="responseNode"></a2ui-controller>
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
  openItems = new Set<number>();
  preconfiguredRoutes = Object.values(PRECONFIGURED_ROUTES) as any;
  isOrganizerAvailable: boolean = false;

  responseNode: any = null;

  private readonly organizerRouteNodeCache = new WeakMap<object, Record<string, unknown>>();

  private demoService = inject(DemoService);
  private plannerAgentGuid: string | null = null;
  private chatSub: Subscription | null = null;

  constructor(private gateway: GatewayService) {
    this.chatSub = this.gateway.chat$.subscribe((msg: ChatMessage) => {
      // if (
      //   msg.guid === this.plannerAgentGuid &&
      //   msg.result &&
      //   (msg.result.beginRendering || msg.result.surfaceUpdate)
      // ) {
      //   this.responseNode = msg.result;
      // }
    });

    effect(async () => {
      const activeDemoKey = this.demoService.activeDemo();
      const activeDemo = DEMO_CONFIG[activeDemoKey] as any;

      this.isOrganizerAvailable =
        activeDemo.agent === 'planner_with_memory' || activeDemo.agent === 'simulator_with_failure';

      // const newPlannerAgent = await this.gateway.addAgent('planner_with_memory');
      // this.plannerAgentGuid = newPlannerAgent;
      // console.log('new msg sending!', this.gateway, newPlannerAgent);
      // this.gateway.sendBroadcast(`list the top 3 best routes`, [newPlannerAgent], true);
    });
  }

  ngOnDestroy(): void {
    this.chatSub?.unsubscribe();
  }

  /** A2UI surface for a preconfigured route row (replaces ScoreCard). */
  organizerRouteNode(route: any): Record<string, unknown> {
    const cached = this.organizerRouteNodeCache.get(route);
    if (cached) return cached;

    const title = route?.name ?? 'Route';
    const sid = String(route?.route_id ?? 'route');
    const geojson = route?.route_data;
    const built: Record<string, unknown> = {
      surfaceUpdate: {
        surfaceId: 'sim_results',
        components: [
          {
            id: 'tag',
            component: {
              Text: {
                text: {
                  literalString: 'SIMULATED',
                },
                usageHint: 'label',
              },
            },
          },
          {
            id: 'sim-meta',
            component: {
              Text: {
                text: {
                  literalString: '#7f5b  26/04/09  02:30:00 PM',
                },
                usageHint: 'caption',
              },
            },
          },
          {
            id: 'tag-row',
            component: {
              Row: {
                children: {
                  explicitList: ['tag', 'sim-meta'],
                },
              },
            },
          },
          {
            id: 'title',
            component: {
              Text: {
                text: {
                  literalString: title,
                },
                usageHint: 'h2',
              },
            },
          },
          {
            id: 'left-col',
            component: {
              Column: {
                children: {
                  explicitList: ['tag-row', 'title'],
                },
              },
            },
          },
          {
            id: 'score-num',
            component: {
              Text: {
                text: {
                  literalString: '85',
                },
                usageHint: 'h1',
              },
            },
          },
          {
            id: 'score-lbl',
            component: {
              Text: {
                text: {
                  literalString: 'Score',
                },
                usageHint: 'caption',
              },
            },
          },
          {
            id: 'score-col',
            component: {
              Column: {
                children: {
                  explicitList: ['score-num', 'score-lbl'],
                },
              },
            },
          },
          {
            id: 'header',
            component: {
              Row: {
                children: {
                  explicitList: ['left-col', 'score-col'],
                },
              },
            },
          },
          {
            id: 'bar-left',
            component: {
              Text: {
                text: {
                  literalString: '#7f5b  26/04/09  02:30:00 PM',
                },
                usageHint: 'caption',
              },
            },
          },
          {
            id: 'bar-right',
            component: {
              Text: {
                text: {
                  literalString: 'SCORE 85%',
                },
                usageHint: 'caption',
              },
            },
          },
          {
            id: 'bar',
            component: {
              Row: {
                children: {
                  explicitList: ['bar-left', 'bar-right'],
                },
              },
            },
          },
          {
            id: 'dist-l',
            component: {
              Text: {
                text: {
                  literalString: 'Total distance',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'dist-v',
            component: {
              Text: {
                text: {
                  literalString: '26.2 miles',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'dist-r',
            component: {
              Row: {
                children: {
                  explicitList: ['dist-l', 'dist-v'],
                },
              },
            },
          },
          {
            id: 'part-l',
            component: {
              Text: {
                text: {
                  literalString: 'Participants (expected/attendance)',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'part-v',
            component: {
              Text: {
                text: {
                  literalString: '10,000/5',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'part-r',
            component: {
              Row: {
                children: {
                  explicitList: ['part-l', 'part-v'],
                },
              },
            },
          },
          {
            id: 'spec-l',
            component: {
              Text: {
                text: {
                  literalString: 'Spectators (expected/attendance)',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'spec-v',
            component: {
              Text: {
                text: {
                  literalString: '—',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'spec-r',
            component: {
              Row: {
                children: {
                  explicitList: ['spec-l', 'spec-v'],
                },
              },
            },
          },
          {
            id: 'peak-l',
            component: {
              Text: {
                text: {
                  literalString: 'Peak Hour Volume',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'peak-v',
            component: {
              Text: {
                text: {
                  literalString: '—',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'peak-r',
            component: {
              Row: {
                children: {
                  explicitList: ['peak-l', 'peak-v'],
                },
              },
            },
          },
          {
            id: 'd1',
            component: {
              Divider: {},
            },
          },
          {
            id: 'safe-l',
            component: {
              Text: {
                text: {
                  literalString: 'Safety Score',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'safe-v',
            component: {
              Text: {
                text: {
                  literalString: '—',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'safe-r',
            component: {
              Row: {
                children: {
                  explicitList: ['safe-l', 'safe-v'],
                },
              },
            },
          },
          {
            id: 'run-l',
            component: {
              Text: {
                text: {
                  literalString: 'Runner Experience',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'run-v',
            component: {
              Text: {
                text: {
                  literalString: '—',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'run-r',
            component: {
              Row: {
                children: {
                  explicitList: ['run-l', 'run-v'],
                },
              },
            },
          },
          {
            id: 'city-l',
            component: {
              Text: {
                text: {
                  literalString: 'City Disruption',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'city-v',
            component: {
              Text: {
                text: {
                  literalString: '—',
                },
                usageHint: 'body',
              },
            },
          },
          {
            id: 'city-r',
            component: {
              Row: {
                children: {
                  explicitList: ['city-l', 'city-v'],
                },
              },
            },
          },
          {
            id: 'd2',
            component: {
              Divider: {},
            },
          },
          {
            id: 'rerun-txt',
            component: {
              Text: {
                text: {
                  literalString: 'Show route',
                },
              },
            },
          },
          {
            id: 'rerun-btn',
            component: {
              Button: {
                child: 'rerun-txt',
                action: {
                  name: 'show_plan',
                  payload: route?.name,
                },
                primary: {
                  literalBoolean: true,
                },
              },
            },
          },

          {
            id: 'opencard-txt',
            component: {
              Text: {
                text: {
                  literalString: 'Open report',
                },
              },
            },
          },
          {
            id: 'opencard-btn',
            component: {
              Button: {
                child: 'opencard-txt',
                action: {
                  name: 'open_card',
                },
                primary: {
                  literalBoolean: true,
                },
              },
            },
          },

          {
            id: 'buttons-r',
            component: {
              Row: {
                children: {
                  explicitList: ['opencard-btn', 'rerun-btn'],
                },
              },
            },
          },
          {
            id: 'content',
            component: {
              Column: {
                children: {
                  explicitList: [
                    'header',
                    'bar',
                    'dist-r',
                    'part-r',
                    'spec-r',
                    'peak-r',
                    'd1',
                    'safe-r',
                    'run-r',
                    'city-r',
                    'd2',
                    'buttons-r',
                  ],
                },
              },
            },
          },
          {
            id: 'card',
            component: {
              Card: {
                child: 'content',
              },
            },
          },
        ],
      },
    };
    this.organizerRouteNodeCache.set(route, built);
    return built;
  }

  toggle(index: number): void {
    if (this.openItems.has(index)) {
      this.openItems.delete(index);
    } else {
      this.openItems.add(index);
    }
  }

  onOrganizerClick(): void {
    console.log('Organizer');
  }

  logStripClassic(e: any, route: any): void {
    console.log('log', route);
    window.dispatchEvent(
      new CustomEvent('gateway:routeGeojson', { detail: { geojson: route.route_data } }),
    );
  }

  async runSimulation(e: any, name: string): Promise<void> {
    console.log('name', name);
    e.stopPropagation();
    const newPlannerAgent = await this.gateway.addAgent('planner_with_memory');

    this.gateway.sendBroadcast(`Run Simulation for ${name}`, [newPlannerAgent]);
  }
}
