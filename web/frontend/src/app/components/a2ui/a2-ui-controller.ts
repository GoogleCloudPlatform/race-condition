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

// TODO :: Nick convert to https://github.com/google/A2UI/tree/main/renderers/angular
import { Component, inject, Input, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GatewayService } from '../../gateway.service';
import { AgentScreenComponent } from '../ChatNavPanel/screens/AgentScreen/AgentScreen';
import cacheRoute01 from '../../../../cached_routes/cache-1.json';
import cacheRoute02 from '../../../../cached_routes/cache-2.json';
import cacheRoute03 from '../../../../cached_routes/cache-3.json';
import { DemoService } from '../DemoOverlay/demo.service';

const A2UI_COMPONENTS = [
  'Text',
  'Image',
  'Icon',
  'Video',
  'AudioPlayer',
  'Divider',
  'Row',
  'Column',
  'List',
  'Card',
  'Tabs',
  'Modal',
  'Button',
  'CheckBox',
  'TextField',
  'DateTimeInput',
  'MultipleChoice',
  'Slider',
];

@Component({
  selector: 'a2ui-controller',
  standalone: true,
  imports: [CommonModule],
  template: `
    <!-- [START a2ui_template_entry] -->
    <div *ngIf="rootNode" class="a2ui-controller">
      <ng-container *ngTemplateOutlet="renderer; context: { node: rootNode }"></ng-container>
    </div>

    <ng-template #renderer let-node="node">
      <ng-container *ngIf="node">
        <div
          [class]="
            'a2ui-' +
            getType(node) +
            (isExpandableSummaryCard(node) ? ' a2ui-Card-expandable' : '') +
            (getType(node) === 'Card' && isFinancialRefusalSurface()
              ? ' a2ui-Card--financial-refusal'
              : getType(node) === 'Card' && isFinancialUpdateSurface()
                ? ' a2ui-Card--financial-update'
                : getType(node) === 'Card' && isRootCardListRoutesSurface(node)
                  ? ' a2ui-Card--route-list'
                  : '')
          "
          [attr.data-id]="getId(node)"
          [attr.data-demo]="demoService.activeDemo()"
          [class.expanded]="isExpandableSummaryCard(node) && isCardExpanded(node)"
          (click)="onExpandableShellClick($event, node)"
        >
          <ng-container [ngSwitch]="getType(node)">
            <!-- [END a2ui_template_entry] -->
            <!-- Layout Containers -->
            <ng-container *ngSwitchCase="'Card'">
              <ng-container *ngIf="isExpandableSummaryCard(node); else cardPlain">
                <div
                  class="a2ui-Card-expandable-summary"
                  role="button"
                  tabindex="0"
                  [attr.aria-expanded]="isCardExpanded(node)"
                  (keydown)="onExpandableSummaryKeydown($event, node)"
                >
                  <!-- <span class="material-icons a2ui-Card-expandable-chevron">expand_more</span> -->
                  <div class="a2ui-Card-expandable-summary-main">
                    <ng-container
                      *ngTemplateOutlet="
                        renderer;
                        context: { node: resolveNode(getExpandableHeaderChildRef(node)) }
                      "
                    ></ng-container>
                  </div>
                </div>
                <div
                  class="a2ui-Card-expandable-body-wrap"
                  [class.a2ui-Card-expandable-body-wrap--open]="isCardExpanded(node)"
                  [attr.aria-hidden]="!isCardExpanded(node)"
                >
                  <div class="a2ui-Card-expandable-body-inner">
                    <div
                      class="a2ui-Column a2ui-Card-expandable-body"
                      [attr.data-id]="getExpandableColumnDataId(node)"
                    >
                      <ng-container *ngFor="let child of getExpandableMiddleChildRefs(node)">
                        <ng-container
                          *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                        ></ng-container>
                      </ng-container>
                    </div>
                  </div>
                </div>
                <div class="a2ui-Card-expandable-footer">
                  <ng-container
                    *ngTemplateOutlet="
                      renderer;
                      context: { node: resolveNode(getExpandableFooterChildRef(node)) }
                    "
                  ></ng-container>
                </div>
              </ng-container>
              <ng-template #cardPlain>
                <ng-container *ngFor="let child of getChildren(node)">
                  <ng-container
                    *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                  ></ng-container>
                </ng-container>
              </ng-template>
            </ng-container>

            <!-- [START a2ui_template_column] -->
            <ng-container *ngSwitchCase="'Column'">
              <ng-container *ngFor="let child of getChildren(node)">
                <ng-container
                  *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                ></ng-container>
              </ng-container>
            </ng-container>
            <!-- [END a2ui_template_column] -->

            <ng-container *ngSwitchCase="'Row'">
              <ng-container *ngIf="isImageTextRow(node); else normalRow">
                <div class="image-text-row">
                  <img
                    [src]="getImageFromRow(node)"
                    [class]="
                      'a2ui-image ' + 'image-' + getUsageHint(resolveNode(getChildren(node)[0]))
                    "
                  />
                  <span class="overlay-text">{{ getTextFromRow(node) }}</span>
                </div>
              </ng-container>
              <ng-template #normalRow>
                <ng-container *ngFor="let child of getChildren(node)">
                  <ng-container
                    *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                  ></ng-container>
                </ng-container>
              </ng-template>
            </ng-container>

            <ng-container *ngSwitchCase="'List'">
              <ng-container *ngFor="let child of getChildren(node)">
                <ng-container
                  *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                ></ng-container>
              </ng-container>
            </ng-container>

            <ng-container *ngSwitchCase="'Tabs'">
              <div class="tabs-header">
                <button
                  *ngFor="let tab of getTabItems(node); let i = index"
                  [class.active]="isActiveTab(node, i)"
                  (click)="setActiveTab(node, i)"
                >
                  {{ getTabTitle(tab) }}
                </button>
              </div>
              <div class="tabs-content">
                <ng-container *ngFor="let tab of getTabItems(node); let i = index">
                  <ng-container *ngIf="isActiveTab(node, i)">
                    <ng-container
                      *ngTemplateOutlet="renderer; context: { node: resolveNode(getTabChild(tab)) }"
                    ></ng-container>
                  </ng-container>
                </ng-container>
              </div>
            </ng-container>

            <ng-container *ngSwitchCase="'Modal'">
              <div class="modal-entry-point" (click)="openModal(node)">
                <ng-container
                  *ngTemplateOutlet="
                    renderer;
                    context: { node: resolveNode(getModalEntryPoint(node)) }
                  "
                ></ng-container>
              </div>
              <div *ngIf="isModalOpen(node)" class="modal-backdrop" (click)="closeModal(node)">
                <div class="modal-panel" (click)="$event.stopPropagation()">
                  <button class="modal-close" (click)="closeModal(node)" aria-label="Close">
                    <span class="material-icons">close</span>
                  </button>
                  <div class="modal-content">
                    <ng-container
                      *ngTemplateOutlet="
                        renderer;
                        context: { node: resolveNode(getModalContent(node)) }
                      "
                    ></ng-container>
                  </div>
                </div>
              </div>
            </ng-container>

            <!-- [START a2ui_template_display] -->
            <!-- Display Elements -->
            <span *ngSwitchCase="'Text'" [class]="'text-' + getUsageHint(node)">
              {{ getText(node) }}
            </span>

            <span *ngSwitchCase="'Icon'" [class]="'material-icons icon'">
              {{ getIconName(node) }}
            </span>

            <img
              *ngSwitchCase="'Image'"
              [src]="getUrl(node)"
              [class]="'a2ui-image ' + 'image-' + getUsageHint(node)"
            />
            <!-- [END a2ui_template_display] -->

            <video
              *ngSwitchCase="'Video'"
              [src]="getUrl(node)"
              controls
              [attr.autoplay]="isAutoplay(node) || null"
              [attr.loop]="isLoop(node) || null"
              [attr.muted]="isMuted(node) || null"
              [attr.playsinline]="isPlaysinline(node) || null"
            ></video>

            <audio
              *ngSwitchCase="'AudioPlayer'"
              [src]="getUrl(node)"
              controls
              [attr.autoplay]="isAutoplay(node) || null"
              [attr.loop]="isLoop(node) || null"
              [attr.muted]="isMuted(node) || null"
            ></audio>

            <div
              *ngSwitchCase="'Divider'"
              class="divider"
              [class.horizontal]="getAxis(node) === 'horizontal'"
              [class.vertical]="getAxis(node) === 'vertical'"
            ></div>

            <!-- [START a2ui_template_button] -->
            <!-- Interactive Controls -->
            <ng-container *ngSwitchCase="'Button'">
              <button
                *ngIf="!(isScorecardExpandToggleButton(node) && alwaysExpandExpandableCards)"
                [class.primary]="isPrimary(node)"
                [class.loading]="loadingButtonIds.has(getId(node))"
                [class.a2ui-Button-runSimulation]="isRunSimulationButton(node)"
                [disabled]="loadingButtonIds.has(getId(node))"
                (click)="handleButtonClick($event, node)"
              >
                <span *ngIf="isScorecardExpandToggleButton(node)" class="material-icons unfold">{{
                  isOpenCardExpanded(node) ? 'unfold_less' : 'unfold_more'
                }}</span>
                <ng-container *ngIf="isRunSimulationButton(node)">
                  <span class="a2ui-Button-runSimulation-stack">
                    <span
                      class="a2ui-Button-runSimulation-layer"
                      [class.is-visible]="!loadingButtonIds.has(getId(node))"
                    >
                      <span class="material-icons">play_arrow</span>
                      <ng-container *ngFor="let child of getChildren(node)">
                        <ng-container
                          *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                        ></ng-container>
                      </ng-container>
                    </span>
                    <span
                      class="a2ui-Button-runSimulation-layer"
                      [class.is-visible]="loadingButtonIds.has(getId(node))"
                    >
                      <span class="run-simulation-running-label">Running...</span>
                    </span>
                  </span>
                </ng-container>
                <ng-container *ngIf="!isRunSimulationButton(node)">
                  <ng-container
                    *ngIf="
                      isScorecardExpandToggleButton(node) && isOpenCardExpanded(node);
                      else scorecardToggleLabel
                    "
                    >Close report</ng-container
                  >
                  <ng-template #scorecardToggleLabel>
                    <ng-container *ngFor="let child of getChildren(node)">
                      <ng-container
                        *ngTemplateOutlet="renderer; context: { node: resolveNode(child) }"
                      ></ng-container>
                    </ng-container>
                  </ng-template>
                </ng-container>
              </button>
            </ng-container>
            <!-- [END a2ui_template_button] -->

            <input
              *ngSwitchCase="'TextField'"
              [type]="getFieldType(node)"
              [placeholder]="getLabel(node)"
              [value]="getText(node)"
            />

            <div class="datetime-input-wrapper" *ngSwitchCase="'DateTimeInput'">
              <span class="material-icons datetime-icon">
                {{ getDateTimeIcon(node) }}
              </span>
              <input
                [type]="getDateTimeInputType(node)"
                [value]="getDateTimeValue(node)"
                class="datetime-input"
              />
            </div>

            <div class="a2ui-Slider" *ngSwitchCase="'Slider'">
              <div class="slider-track">
                <div class="label">{{ getLabel(node) }}</div>
                <div id="fill" class="gradient-fill">
                  <div class="thumb-line"></div>
                </div>
              </div>
              <input
                type="range"
                [value]="getValue(node)"
                [min]="getMinValue(node)"
                [max]="getMaxValue(node)"
                (input)="handleSliderChange(node, $event)"
              />
            </div>

            <div class="a2ui-CheckBox" *ngSwitchCase="'CheckBox'">
              <label class="checkbox-label">
                <input type="checkbox" [checked]="getValue(node)" />
                <span class="checkbox-custom"></span>
                <span class="checkbox-text">{{ getLabel(node) }}</span>
              </label>
            </div>
            <!-- (change)="handleCheckboxChange(node, $event)" -->

            <div class="multiple-choice-options" *ngSwitchCase="'MultipleChoice'">
              <button
                *ngFor="let option of getOptions(node)"
                class="multiple-choice-option"
                [class.selected]="isOptionSelected(node, option.value)"
                (click)="handleButtonClick($event, node)"
              >
                <span class="material-icons mc-icon">
                  {{
                    isOptionSelected(node, option.value) ? 'check_circle' : 'radio_button_unchecked'
                  }}
                </span>
                <span class="mc-label">{{ resolveOptionLabel(option) }}</span>
              </button>
            </div>

            <!-- Fallback for unknown types -->
            <div *ngSwitchDefault class="unknown-component">
              Unknown component type: {{ getType(node) }}
            </div>
          </ng-container>
        </div>
      </ng-container>
    </ng-template>
  `,
  styleUrl: './a2-ui-controller.scss',
})
export class A2uiControllerComponent implements OnChanges {
  @Input() surface: any;
  @Input() node: any;

  @Input() runCached: any;
  @Input() plannerAgentGuid: any;
  /** When true, expandable summary cards stay expanded and cannot be toggled closed. */
  @Input() alwaysExpandExpandableCards = false;
  private componentsMap: Map<string, any> = new Map();
  private activeTabMap: Map<string, number> = new Map();
  private modalOpenMap: Map<string, boolean> = new Map();
  private selectionsMap: Map<string, string[]> = new Map();
  loadingButtonIds: Set<string> = new Set();
  expandedCardIds: Set<string> = new Set();
  rootNode: any = null;

  private agentScreen = inject(AgentScreenComponent);

  demoService = inject(DemoService);

  constructor(private gateway: GatewayService) {}

  // actions.js
  actionRegistry = {
    run_simulation: () => {
      console.log('Simulation started!');

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

    run_simulation_with_route_data: (payload?: any) => {
      this.gateway.sendBroadcast(
        `Run simulation with the best route available`,
        [this.agentScreen.currentAgent!.sessionId],
        true,
      );
    },
    stop_simulation: () => {
      console.log('Simulation stopped.');
    },

    show_route: (payload?: { seed?: unknown }) => {
      if (this.runCached) {
        const cachedRoutes = {
          'dd82048d-914d-4bbc-99f8-d44c33c9834c': cacheRoute01,

          'seed-0003-east-side-explorer-i9j0k1l2': cacheRoute02,
          'seed-0004-grand-loop-m3n4o5p6': cacheRoute03,
        };

        window.dispatchEvent(
          new CustomEvent('gateway:routeGeojson', {
            detail: { geojson: cachedRoutes[payload?.seed as keyof typeof cachedRoutes] },
          }),
        );
      } else {
        this.gateway.sendBroadcast(
          `Get the route for the seed ${payload?.seed}`,
          [this.plannerAgentGuid],
          true,
        );
      }
    },
  };

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['node'] && this.node) {
      // Parse if it's a string
      if (typeof this.node === 'string') {
        try {
          this.node = JSON.parse(this.node);
        } catch (e) {
          console.error('Failed to parse node string:', e);
        }
      }
      this.processNode();
    }
    if (changes['surface'] && this.surface) {
      this.buildComponentsMap();
    }
  }

  /** `open_card` or `organizer_show_scorecard`: toggles expandable summary / report. */
  isScorecardExpandToggleButton(node: any): boolean {
    const actionData = this.getData(node)?.action;
    const name = this.resolveValue(actionData?.name);
    return name === 'open_card' || name === 'organizer_show_scorecard';
  }

  /** Whether the expandable card containing this scorecard toggle button is expanded. */
  isOpenCardExpanded(node: any): boolean {
    const card = this.findInnermostCardContaining(this.getId(node));
    return !!card && this.isCardExpanded(card);
  }

  isRunSimulationButton(node: any): boolean {
    const actionData = this.getData(node)?.action;
    return this.resolveValue(actionData?.name) === 'run_simulation';
  }

  handleButtonClick(event: any, node: any): void {
    const actionData = this.getData(node)?.action;
    const actionName = this.resolveValue(actionData?.name);
    const payload = actionData?.payload;

    if (actionName === 'open_card' || actionName === 'organizer_show_scorecard') {
      const card = this.findInnermostCardContaining(this.getId(node));
      if (card) {
        this.toggleCardExpand(event, card);
      }
      return;
    }

    if (actionName === 'show_route') {
      // @ts-expect-error
      const instant = this.actionRegistry[actionName];
      if (instant) instant(payload);
      return;
    }

    this.loadingButtonIds.add(this.getId(node));

    // @ts-expect-error
    const actionFunc = this.actionRegistry[actionName];

    if (actionFunc) {
      actionFunc(payload);
    } else {
      console.warn(`Action "${actionName}" is not defined in the registry.`);
    }
  }

  private processNode(): void {
    if (this.node.surfaceUpdate) {
      this.buildComponentsMap(this.node.surfaceUpdate.components);
      this.rootNode = this.findRootComponent();
    } else if (this.node.component || this.getType(this.node) !== 'Unknown') {
      this.rootNode = this.node;
    } else {
      console.warn('Unknown node structure:', this.node);
      this.rootNode = null;
    }
  }

  private buildComponentsMap(components?: any[]): void {
    this.componentsMap.clear();

    const componentsArray =
      components || this.surface?.components || this.node?.surfaceUpdate?.components;

    if (!componentsArray) return;

    for (const item of componentsArray) {
      if (item.id) {
        this.componentsMap.set(item.id, item);
      }
    }
    // console.log('Components map built:', this.componentsMap);
  }

  private findRootComponent(): any {
    const allIds = new Set(this.componentsMap.keys());
    const referencedIds = new Set<string>();

    // Debug: log all components
    // console.log(
    //   'All components:',
    //   Array.from(this.componentsMap.entries()).map(([id, comp]) => ({
    //     id,
    //     type: this.getType(comp),
    //     children: this.getChildren(comp),
    //   })),
    // );

    for (const component of this.componentsMap.values()) {
      const children = this.getChildren(component);
      for (const child of children) {
        if (typeof child === 'string') {
          referencedIds.add(child);
        }
      }
      // Tab children are not returned by getChildren, so collect them separately
      for (const tab of this.getTabItems(component)) {
        const childId = this.getTabChild(tab);
        if (childId) {
          referencedIds.add(childId);
        }
      }
      // Modal children are not returned by getChildren, so collect them separately
      if (this.getType(component) === 'Modal') {
        const data = this.getData(component);
        if (data.entryPointChild) referencedIds.add(data.entryPointChild);
        if (data.contentChild) referencedIds.add(data.contentChild);
      }
    }

    // console.log('Referenced IDs:', Array.from(referencedIds));
    // console.log(
    //   'Unreferenced IDs (potential roots):',
    //   Array.from(allIds).filter((id) => !referencedIds.has(id)),
    // );

    for (const id of allIds) {
      if (!referencedIds.has(id)) {
        // console.log('Found root component ID:', id);
        return this.componentsMap.get(id);
      }
    }

    return Array.from(this.componentsMap.values())[0] || null;
  }

  resolveNode(nodeOrId: any): any {
    if (typeof nodeOrId === 'string') {
      const resolved = this.componentsMap.get(nodeOrId);
      // console.log('Resolving ID:', nodeOrId, 'to:', resolved, 'Type:', this.getType(resolved));
      return resolved || null;
    }
    return nodeOrId;
  }

  getType(node: any): string {
    if (!node) return '';

    if (node.component) {
      const componentKeys = Object.keys(node.component);
      const typeKey = componentKeys.find((k) => A2UI_COMPONENTS.includes(k));
      return typeKey || 'Unknown';
    }

    const keys = Object.keys(node);
    const typeKey = keys.find((k) => A2UI_COMPONENTS.includes(k));

    return typeKey || 'Unknown';
  }

  getData(node: any): any {
    if (!node) return {};

    if (node.component) {
      const type = this.getType(node);
      return node.component[type] || {};
    }

    const type = this.getType(node);
    return node[type] || node;
  }

  getId(node: any): string {
    if (node.id) return node.id;
    const data = this.getData(node);
    return data.id || '';
  }

  cardExpansionKey(cardNode: any): string {
    const sid = this.node?.surfaceUpdate?.surfaceId as string | undefined;
    const cardId = this.getId(cardNode);
    return sid ? `${sid}:${cardId}` : cardId;
  }

  isFinancialRefusalSurface(): boolean {
    const sid = this.node?.surfaceUpdate?.surfaceId as string | undefined;
    return typeof sid === 'string' && sid.includes('financial_refusal');
  }
  isFinancialUpdateSurface(): boolean {
    const sid = this.node?.surfaceUpdate?.surfaceId as string | undefined;
    return typeof sid === 'string' && sid.includes('financial_update');
  }

  /** Route list shell: only the graph root Card (wraps the List), not per-route cards inside. */
  isRootCardListRoutesSurface(cardNode: any): boolean {
    const sid = this.node?.surfaceUpdate?.surfaceId as string | undefined;
    if (typeof sid !== 'string' || !sid.includes('route_list')) return false;
    if (!cardNode || !this.rootNode) return false;
    if (this.getType(this.rootNode) !== 'Card') return false;
    return this.getId(cardNode) === this.getId(this.rootNode);
  }

  isExpandableSummaryCard(node: any): boolean {
    const children = this.getChildren(node);
    if (children.length !== 1) return false;
    const col = this.resolveNode(children[0]);
    if (!col || this.getType(col) !== 'Column') return false;
    const colChildren = this.getChildren(col);
    // Header + middle + footer (last row always visible, e.g. button).
    if (colChildren.length < 3) return false;
    const first = this.resolveNode(colChildren[0]);
    const id = first != null ? this.getId(first) : '';
    // Exact `header` (single-card surfaces) or `header-1` style (multiple cards in one surface).
    return id === 'header' || /^header-/.test(id);
  }

  getExpandableColumnRef(cardNode: any): any {
    return this.getChildren(cardNode)[0];
  }

  getExpandableHeaderChildRef(cardNode: any): any {
    const col = this.resolveNode(this.getExpandableColumnRef(cardNode));
    return this.getChildren(col)[0];
  }

  /** Column children between header and last row (shown only when expanded). */
  getExpandableMiddleChildRefs(cardNode: any): any[] {
    const col = this.resolveNode(this.getExpandableColumnRef(cardNode));
    const list = this.getChildren(col);
    if (list.length <= 2) return [];
    return list.slice(1, -1);
  }

  /** Last column child (e.g. primary action); visible collapsed and expanded. */
  getExpandableFooterChildRef(cardNode: any): any {
    const col = this.resolveNode(this.getExpandableColumnRef(cardNode));
    const list = this.getChildren(col);
    return list[list.length - 1];
  }

  getExpandableColumnDataId(cardNode: any): string {
    const col = this.resolveNode(this.getExpandableColumnRef(cardNode));
    return this.getId(col);
  }

  isCardExpanded(cardNode: any): boolean {
    if (this.alwaysExpandExpandableCards) return true;
    return this.expandedCardIds.has(this.cardExpansionKey(cardNode));
  }

  toggleCardExpand(event: Event, cardNode: any): void {
    if (this.alwaysExpandExpandableCards) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    const key = this.cardExpansionKey(cardNode);
    if (this.expandedCardIds.has(key)) {
      this.expandedCardIds.delete(key);
    } else {
      this.expandedCardIds.add(key);
    }
    this.expandedCardIds = new Set(this.expandedCardIds);
  }

  /** Forwards to expandable card click handling only on expandable summary card shells. */
  onExpandableShellClick(event: MouseEvent, cardNode: any): void {
    if (!this.isExpandableSummaryCard(cardNode)) return;
    this.onExpandableCardClick(event, cardNode);
  }

  /** Toggle expand/collapse from the card surface; ignores clicks on embedded controls. */
  onExpandableCardClick(event: MouseEvent, cardNode: any): void {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.closest('button, a, input, select, textarea')) {
      return;
    }
    const roleBtn = target.closest('[role="button"]');
    if (roleBtn && !roleBtn.classList.contains('a2ui-Card-expandable-summary')) {
      return;
    }
    this.toggleCardExpand(event, cardNode);
  }

  /** Innermost Card on the path from root to the component with the given id (e.g. a Button inside the card). */
  private findInnermostCardContaining(
    componentId: string,
    n: any = this.rootNode,
    cardStack: any[] = [],
  ): any | null {
    if (!n || !componentId) return null;
    const type = this.getType(n);
    const stack = type === 'Card' ? [...cardStack, n] : cardStack;
    if (this.getId(n) === componentId) {
      const len = stack.length;
      return len > 0 ? stack[len - 1]! : null;
    }
    if (type === 'Modal') {
      const data = this.getData(n);
      for (const ref of [data.entryPointChild, data.contentChild]) {
        if (!ref) continue;
        const child = this.resolveNode(ref);
        const found = this.findInnermostCardContaining(componentId, child, stack);
        if (found) return found;
      }
      return null;
    }
    if (type === 'Tabs') {
      for (const tab of this.getTabItems(n)) {
        const child = this.resolveNode(this.getTabChild(tab));
        const found = this.findInnermostCardContaining(componentId, child, stack);
        if (found) return found;
      }
      return null;
    }
    for (const childRef of this.getChildren(n)) {
      const child = this.resolveNode(childRef);
      const found = this.findInnermostCardContaining(componentId, child, stack);
      if (found) return found;
    }
    return null;
  }

  onExpandableSummaryKeydown(event: KeyboardEvent, cardNode: any): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.toggleCardExpand(event, cardNode);
    }
  }

  getTabItems(node: any): any[] {
    const data = this.getData(node);
    return data.tabItems || [];
  }

  getTabTitle(tab: any): string {
    const title = tab.title;
    if (!title) return '';
    if (typeof title === 'string') return title;
    if (title.literalString) return title.literalString;
    return String(title);
  }

  getTabChild(tab: any): string {
    return tab.child || '';
  }

  isActiveTab(node: any, index: number): boolean {
    return (this.activeTabMap.get(this.getId(node)) ?? 0) === index;
  }

  setActiveTab(node: any, index: number): void {
    this.activeTabMap.set(this.getId(node), index);
  }

  isLayout(node: any): boolean {
    const type = this.getType(node);
    return ['Card', 'Column', 'Row', 'List', 'Modal', 'Tabs'].includes(type);
  }

  getChildren(node: any): any[] {
    const data = this.getData(node);

    let children = data.children || data.child || data.items;
    if (!children && data.slots) {
      children = data.slots.children || data.slots.child || data.slots.items;
    }

    if (!children) return [];
    if (Array.isArray(children)) return children;
    if (children.explicitList) return children.explicitList;

    const result = [children];
    // console.log('getChildren for', this.getType(node), ':', result);
    return result;
  }

  getChild(node: any): any {
    const children = this.getChildren(node);
    return children[0] || null;
  }

  resolveValue(value: any): any {
    if (value && typeof value === 'object') {
      if ('literalString' in value) return value.literalString;
      if ('literalNumber' in value) return value.literalNumber;
      if ('literalBoolean' in value) return value.literalBoolean;
      if ('literalArray' in value) return value.literalArray;
      if ('path' in value) return `[${value.path}]`;
    }
    return value;
  }

  getText(node: any): string {
    const data = this.getData(node);
    const text = data.text || data.label || '';
    const resolved = this.resolveValue(text);
    return resolved != null ? String(resolved) : '';
  }

  getIconName(node: any): string {
    const data = this.getData(node);
    const name = data.name || data.text || data.label || '';
    const resolved = this.resolveValue(name);
    return resolved != null ? String(resolved) : '';
  }

  isAutoplay(node: any): boolean {
    return !!this.getData(node).autoplay;
  }

  isLoop(node: any): boolean {
    return !!this.getData(node).loop;
  }

  isMuted(node: any): boolean {
    return !!this.getData(node).muted;
  }

  isPlaysinline(node: any): boolean {
    return !!this.getData(node).playsinline;
  }

  getUrl(node: any): string {
    const data = this.getData(node);
    // console.log('geturl', data);
    return data.url.literalString || data.src.literalString || '';
  }

  getUsageHint(node: any): string {
    const data = this.getData(node);
    return data.usageHint || 'body';
  }

  isPrimary(node: any): boolean {
    const data = this.getData(node);
    return data.primary || false;
  }

  getAxis(node: any): string {
    const data = this.getData(node);
    return data.axis || 'horizontal';
  }

  getLabel(node: any): string {
    const data = this.getData(node);
    const label = data.label || '';
    const resolved = this.resolveValue(label);
    return resolved != null ? String(resolved) : '';
  }

  getFieldType(node: any): string {
    const data = this.getData(node);
    const typeMap: Record<string, string> = {
      shortText: 'text',
      longText: 'textarea',
      number: 'number',
      date: 'date',
      obscured: 'password',
    };
    return typeMap[data.textFieldType || 'shortText'] || 'text';
  }

  getDateTimeInputType(node: any): string {
    const data = this.getData(node);
    if (data.enableDate && data.enableTime) return 'datetime-local';
    if (data.enableDate) return 'date';
    if (data.enableTime) return 'time';
    return 'datetime-local';
  }

  getDateTimeIcon(node: any): string {
    const data = this.getData(node);
    if (data.enableDate && data.enableTime) return 'event';
    if (data.enableDate) return 'calendar_today';
    if (data.enableTime) return 'schedule';
    return 'event';
  }

  getDateTimeValue(node: any): string {
    const data = this.getData(node);
    const raw = this.resolveValue(data.value);
    if (!raw) return '';
    try {
      const d = new Date(raw);
      if (isNaN(d.getTime())) return raw;
      if (data.enableDate && data.enableTime) {
        // datetime-local expects "YYYY-MM-DDTHH:MM"
        return d.toISOString().slice(0, 16);
      }
      if (data.enableDate) {
        return d.toISOString().slice(0, 10);
      }
      if (data.enableTime) {
        return d.toISOString().slice(11, 16);
      }
    } catch {
      return raw;
    }
    return raw;
  }

  getValue(node: any): any {
    const data = this.getData(node);
    return this.resolveValue(data.value) ?? 0;
  }

  getMinValue(node: any): number {
    const data = this.getData(node);
    return data.minValue !== undefined ? data.minValue : 0;
  }

  getMaxValue(node: any): number {
    const data = this.getData(node);
    return data.maxValue !== undefined ? data.maxValue : 100;
  }

  handleSliderChange(node: any, event: Event): void {
    const input = event.target as HTMLInputElement;
    const data = this.getData(node);
    // console.log('Slider changed:', {
    //   target: event.target,
    //   curr: event.currentTarget,
    //   id: data.id,
    //   value: input.value,
    //   node: data,
    // });

    const gradientFill = input.parentElement?.querySelector('.gradient-fill') as HTMLElement;
    if (gradientFill) {
      gradientFill.style.setProperty('--inset', 100 - parseInt(input.value) + '%');
    }
  }

  getModalEntryPoint(node: any): any {
    return this.getData(node).entryPointChild || null;
  }

  getModalContent(node: any): any {
    return this.getData(node).contentChild || null;
  }

  isModalOpen(node: any): boolean {
    return this.modalOpenMap.get(this.getId(node)) ?? false;
  }

  openModal(node: any): void {
    this.modalOpenMap.set(this.getId(node), true);
  }

  closeModal(node: any): void {
    this.modalOpenMap.set(this.getId(node), false);
  }

  handleAction(node: any): void {
    const data = this.getData(node);
    if (data.action) {
      // console.log('Action triggered:', data.action);
    }
  }

  isImageTextRow(node: any): boolean {
    const children = this.getChildren(node);
    if (children.length !== 2) return false;

    const child1 = this.resolveNode(children[0]);
    const child2 = this.resolveNode(children[1]);

    const type1 = this.getType(child1);
    const type2 = this.getType(child2);

    return (type1 === 'Image' && type2 === 'Text') || (type1 === 'Text' && type2 === 'Image');
  }

  getImageFromRow(node: any): string {
    const children = this.getChildren(node);
    for (const child of children) {
      const resolved = this.resolveNode(child);
      if (this.getType(resolved) === 'Image') {
        return this.getUrl(resolved);
      }
    }
    return '';
  }

  getTextFromRow(node: any): string {
    const children = this.getChildren(node);
    for (const child of children) {
      const resolved = this.resolveNode(child);
      if (this.getType(resolved) === 'Text') {
        return this.getText(resolved);
      }
    }
    return '';
  }

  getOptions(node: any): any[] {
    return this.getData(node).options || [];
  }

  resolveOptionLabel(option: any): string {
    const label = option.label;
    if (!label) return '';
    const resolved = this.resolveValue(label);
    return resolved != null ? String(resolved) : '';
  }

  isOptionSelected(node: any, value: string): boolean {
    const id = this.getId(node);
    if (this.selectionsMap.has(id)) {
      return this.selectionsMap.get(id)!.includes(value);
    }
    const data = this.getData(node);
    const initial: string[] = this.resolveValue(data.selections) || [];
    return initial.includes(value);
  }
}
