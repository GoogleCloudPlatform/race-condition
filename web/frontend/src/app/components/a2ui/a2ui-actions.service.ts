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

import { inject, Injectable } from '@angular/core';
import { GatewayService } from '../../gateway.service';
import { AgentScreenComponent } from '../ChatNavPanel/screens/AgentScreen/agent-screen.component';
import cacheRoute01 from '../../../../cached_routes/cache-1.json';
import cacheRoute02 from '../../../../cached_routes/cache-2.json';
import cacheRoute03 from '../../../../cached_routes/cache-3.json';
import type { A2uiActionPayload } from './a2ui-surface.model';

export interface A2uiActionDispatchContext {
  runCached: boolean;
  plannerAgentGuid?: string | null;
}

const CACHED_ROUTE_KEYS = [
  'dd82048d-914d-4bbc-99f8-d44c33c9834c',
  'seed-0003-east-side-explorer-i9j0k1l2',
  'seed-0004-grand-loop-m3n4o5p6',
] as const;

type CachedRouteSeed = (typeof CACHED_ROUTE_KEYS)[number];

const CACHED_ROUTES: Record<CachedRouteSeed, unknown> = {
  'dd82048d-914d-4bbc-99f8-d44c33c9834c': cacheRoute01,
  'seed-0003-east-side-explorer-i9j0k1l2': cacheRoute02,
  'seed-0004-grand-loop-m3n4o5p6': cacheRoute03,
};

export type A2uiRegisteredActionName =
  | 'run_simulation'
  | 'run_simulation_with_llm_runners'
  | 'run_simulation_with_route_data'
  | 'stop_simulation'
  | 'show_route';

/** Provide on `A2uiControllerComponent` only — requires `AgentScreenComponent` from an ancestor injector. */
@Injectable()
export class A2uiActionsService {
  private readonly gateway = inject(GatewayService);
  private readonly agentScreen = inject(AgentScreenComponent);

  private static readonly REGISTERED_NAMES: readonly A2uiRegisteredActionName[] = [
    'run_simulation',
    'run_simulation_with_llm_runners',
    'run_simulation_with_route_data',
    'stop_simulation',
    'show_route',
  ];

  dispatchRegisteredAction(
    name: A2uiRegisteredActionName,
    payload: A2uiActionPayload,
    ctx: A2uiActionDispatchContext,
  ): void {
    const handler = this.handlers(ctx)[name];
    if (handler) {
      handler(payload);
    }
  }

  isRegisteredAction(name: string): name is A2uiRegisteredActionName {
    return (A2uiActionsService.REGISTERED_NAMES as readonly string[]).includes(name);
  }

  private handlers(ctx: A2uiActionDispatchContext): Record<A2uiRegisteredActionName, (p: A2uiActionPayload) => void> {
    return {
      run_simulation: () => {
        this.agentScreen.isAgentWorking = true;

        if (this.agentScreen.runCachedMessages) {
          this.agentScreen.runCachedDataStream();
        } else {
          this.gateway.sendBroadcast(
            'Run the simulation for a marathon in Las Vegas for 10,000 runners',
            [this.agentScreen.currentAgent!.sessionId],
            true,
          );
        }
      },
      run_simulation_with_llm_runners: () => {
        this.agentScreen.isAgentWorking = true;

        if (this.agentScreen.runCachedMessages) {
          this.agentScreen.runCachedDataStream();
        } else {
          this.gateway.sendBroadcast(
            'Simulate your best plan with 10 LLM runners on GKE',
            [this.agentScreen.currentAgent!.sessionId],
            true,
          );
        }
      },
      run_simulation_with_route_data: () => {
        this.gateway.sendBroadcast(
          `Run simulation with the best route available`,
          [this.agentScreen.currentAgent!.sessionId],
          true,
        );
      },
      stop_simulation: () => undefined,
      show_route: (payload) => {
        if (ctx.runCached) {
          const seed = (payload as { seed?: string } | undefined)?.seed;
          const geojson =
            seed && this.isCachedRouteSeed(seed) ? CACHED_ROUTES[seed] : undefined;
          window.dispatchEvent(
            new CustomEvent('gateway:routeGeojson', {
              detail: { geojson },
            }),
          );
        } else {
          this.gateway.sendBroadcast(
            `Get the route for the seed ${(payload as { seed?: unknown } | undefined)?.seed}`,
            [ctx.plannerAgentGuid!],
            true,
          );
        }
      },
    };
  }

  private isCachedRouteSeed(seed: string): seed is CachedRouteSeed {
    return (CACHED_ROUTE_KEYS as readonly string[]).includes(seed);
  }
}
