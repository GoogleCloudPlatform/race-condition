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
  booleanAttribute,
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DemoService } from '../DemoOverlay/demo.service';
import { A2uiActionsService, type A2uiActionDispatchContext } from './a2ui-actions.service';
import { A2uiTreeService } from './a2ui-tree.service';
import type {
  A2uiActionPayload,
  A2uiComponentRecord,
  A2uiNode,
  A2uiSurfacePayload,
} from './a2ui-surface.model';

@Component({
  selector: 'a2ui-controller',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './a2-ui-controller.component.html',
  styleUrl: './a2-ui-controller.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [A2uiActionsService],
})
export class A2uiControllerComponent {
  readonly surface = input<A2uiSurfacePayload | undefined>(undefined);
  readonly node = input<unknown>(undefined);

  readonly runCached = input<boolean | undefined>(undefined);
  readonly plannerAgentGuid = input<string | null | undefined>(undefined);
  /** When true, expandable summary cards stay expanded and cannot be toggled closed. */
  readonly alwaysExpandExpandableCards = input(false, { transform: booleanAttribute });
  /**
   * Mirrors agent working state for templates (e.g. run-simulation label). Must be an input so OnPush
   * runs when this flips; reading `AgentScreenComponent` in a method does not trigger child CD.
   */
  readonly isAgentWorking = input(false);

  private readonly tree = inject(A2uiTreeService);
  private readonly actions = inject(A2uiActionsService);

  readonly demoService = inject(DemoService);

  private readonly parsedNode = signal<A2uiNode | null>(null);
  readonly componentsMap = signal<Map<string, A2uiNode>>(new Map());
  readonly rootNode = signal<A2uiNode | null>(null);

  private readonly activeTabMap = signal(new Map<string, number>());
  private readonly modalOpenMap = signal(new Map<string, boolean>());
  private readonly selectionsMap = signal(new Map<string, string[]>());
  readonly loadingButtonIds = signal(new Set<string>());
  readonly expandedCardIds = signal(new Set<string>());

  private readonly actionCtx = computed<A2uiActionDispatchContext>(() => ({
    runCached: !!this.runCached(),
    plannerAgentGuid: this.plannerAgentGuid() ?? undefined,
  }));

  constructor() {
    effect(() => {
      const rawNode = this.node();
      const surfaceVal = this.surface();

      untracked(() => {
        if (rawNode != null && rawNode !== undefined) {
          let parsed: unknown = rawNode;
          if (typeof rawNode === 'string') {
            try {
              parsed = JSON.parse(rawNode);
            } catch (e) {
              console.error('Failed to parse node string:', e);
              this.parsedNode.set(null);
              this.rootNode.set(null);
              return;
            }
          }
          const p = parsed as A2uiNode;
          this.parsedNode.set(p);

          if (p.surfaceUpdate) {
            this.componentsMap.set(
              this.tree.buildComponentsMap(p.surfaceUpdate.components as A2uiComponentRecord[]),
            );
            this.rootNode.set(this.tree.findRootComponent(this.componentsMap()));
          } else if (p.component || this.tree.getType(p) !== 'Unknown') {
            this.rootNode.set(p);
          } else {
            console.warn('Unknown node structure:', p);
            this.rootNode.set(null);
          }
        } else {
          this.parsedNode.set(null);
          this.rootNode.set(null);
        }

        if (surfaceVal) {
          const arr =
            surfaceVal.components ??
            (this.parsedNode()?.surfaceUpdate?.components as A2uiComponentRecord[] | undefined);
          this.componentsMap.set(this.tree.buildComponentsMap(arr));
          const p = this.parsedNode();
          if (p?.surfaceUpdate) {
            this.rootNode.set(this.tree.findRootComponent(this.componentsMap()));
          }
        }
      });
    });

    /** Collapse expandable cards when the active demo or its reset counter changes. */
    effect(() => {
      this.demoService.activeDemo();
      this.demoService.reset();
      untracked(() => {
        this.expandedCardIds.set(new Set());
      });
    });
  }

  getType(node: A2uiNode): string {
    return this.tree.getType(node);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  getData(node: A2uiNode): any {
    return this.tree.getData(node);
  }

  getId(node: A2uiNode): string {
    return this.tree.getId(node);
  }

  resolveNode(nodeOrId: unknown): A2uiNode | null {
    return this.tree.resolveNode(this.componentsMap(), nodeOrId);
  }

  getChildren(node: A2uiNode): unknown[] {
    return this.tree.getChildren(node);
  }

  getTabItems(node: A2uiNode): unknown[] {
    return this.tree.getTabItems(node);
  }

  getTabTitle(tab: unknown): string {
    return this.tree.getTabTitle(tab as Record<string, unknown>);
  }

  getTabChild(tab: unknown): string {
    return this.tree.getTabChild(tab as Record<string, unknown>);
  }

  resolveValue(value: unknown): unknown {
    return this.tree.resolveValue(value);
  }

  isFinancialRefusalSurface(): boolean {
    return this.tree.isFinancialRefusalSurface(this.parsedNode());
  }

  isFinancialUpdateSurface(): boolean {
    return this.tree.isFinancialUpdateSurface(this.parsedNode());
  }

  isRootCardListRoutesSurface(cardNode: A2uiNode): boolean {
    return this.tree.isRootCardListRoutesSurface(
      this.parsedNode(),
      this.rootNode(),
      this.componentsMap(),
      cardNode,
    );
  }

  isExpandableSummaryCard(node: A2uiNode): boolean {
    return this.tree.isExpandableSummaryCard(this.componentsMap(), node);
  }

  getExpandableHeaderChildRef(node: A2uiNode): unknown {
    return this.tree.getExpandableHeaderChildRef(this.componentsMap(), node);
  }

  getExpandableMiddleChildRefs(node: A2uiNode): unknown[] {
    return this.tree.getExpandableMiddleChildRefs(this.componentsMap(), node);
  }

  getExpandableFooterChildRef(node: A2uiNode): unknown {
    return this.tree.getExpandableFooterChildRef(this.componentsMap(), node);
  }

  getExpandableColumnDataId(node: A2uiNode): string {
    return this.tree.getExpandableColumnDataId(this.componentsMap(), node);
  }

  isCardExpanded(cardNode: A2uiNode): boolean {
    if (this.alwaysExpandExpandableCards()) return true;
    return this.expandedCardIds().has(
      this.tree.cardExpansionKey(this.parsedNode(), this.componentsMap(), cardNode),
    );
  }

  toggleCardExpand(event: Event, cardNode: A2uiNode): void {
    if (this.alwaysExpandExpandableCards()) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    const key = this.tree.cardExpansionKey(this.parsedNode(), this.componentsMap(), cardNode);
    this.expandedCardIds.update((s) => {
      const n = new Set(s);
      if (n.has(key)) {
        n.delete(key);
      } else {
        n.add(key);
      }
      return n;
    });
  }

  onExpandableShellClick(event: MouseEvent, cardNode: A2uiNode): void {
    if (!this.isExpandableSummaryCard(cardNode)) return;
    this.onExpandableCardClick(event, cardNode);
  }

  onExpandableCardClick(event: MouseEvent, cardNode: A2uiNode): void {
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

  onExpandableSummaryKeydown(event: KeyboardEvent, cardNode: A2uiNode): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.toggleCardExpand(event, cardNode);
    }
  }

  isActiveTab(node: A2uiNode, index: number): boolean {
    return (this.activeTabMap().get(this.getId(node)) ?? 0) === index;
  }

  setActiveTab(node: A2uiNode, index: number): void {
    const id = this.getId(node);
    this.activeTabMap.update((m) => {
      const n = new Map(m);
      n.set(id, index);
      return n;
    });
  }

  isScorecardExpandToggleButton(node: A2uiNode): boolean {
    return this.tree.isScorecardExpandToggleButton(node);
  }

  isOpenCardExpanded(node: A2uiNode): boolean {
    const card = this.tree.findInnermostCardContaining(
      this.componentsMap(),
      this.rootNode(),
      this.getId(node),
    );
    return !!card && this.isCardExpanded(card);
  }

  isRunSimulationButton(node: A2uiNode): boolean {
    return this.tree.isRunSimulationButton(node);
  }

  handleButtonClick(event: Event, node: A2uiNode): void {
    const actionData = this.getData(node)['action'] as Record<string, unknown> | undefined;
    const actionName = String(this.tree.resolveValue(actionData?.['name']) ?? '');
    const payload = actionData?.['payload'] as A2uiActionPayload;

    if (actionName === 'open_card' || actionName === 'organizer_show_scorecard') {
      const card = this.tree.findInnermostCardContaining(
        this.componentsMap(),
        this.rootNode(),
        this.getId(node),
      );
      if (card) {
        this.toggleCardExpand(event, card);
      }
      return;
    }

    if (actionName === 'show_route') {
      if (this.actions.isRegisteredAction(actionName)) {
        this.actions.dispatchRegisteredAction(actionName, payload, this.actionCtx());
      }
      return;
    }

    this.loadingButtonIds.update((s) => {
      const n = new Set(s);
      n.add(this.getId(node));
      return n;
    });

    if (this.actions.isRegisteredAction(actionName)) {
      this.actions.dispatchRegisteredAction(actionName, payload, this.actionCtx());
    } else {
      console.warn(`Action "${actionName}" is not defined in the registry.`);
    }
  }

  getText(node: A2uiNode): string {
    return this.tree.getText(node);
  }

  getIconName(node: A2uiNode): string {
    return this.tree.getIconName(node);
  }

  getUrl(node: A2uiNode): string {
    return this.tree.getUrl(node);
  }

  getUsageHint(node: A2uiNode | null): string {
    return this.tree.getUsageHint(node);
  }

  isAutoplay(node: A2uiNode): boolean {
    return this.tree.isAutoplay(node);
  }

  isLoop(node: A2uiNode): boolean {
    return this.tree.isLoop(node);
  }

  isMuted(node: A2uiNode): boolean {
    return this.tree.isMuted(node);
  }

  isPlaysinline(node: A2uiNode): boolean {
    return this.tree.isPlaysinline(node);
  }

  isPrimary(node: A2uiNode): boolean {
    return this.tree.isPrimary(node);
  }

  getAxis(node: A2uiNode): string {
    return this.tree.getAxis(node);
  }

  getLabel(node: A2uiNode): string {
    return this.tree.getLabel(node);
  }

  getFieldType(node: A2uiNode): string {
    return this.tree.getFieldType(node);
  }

  getDateTimeInputType(node: A2uiNode): string {
    return this.tree.getDateTimeInputType(node);
  }

  getDateTimeIcon(node: A2uiNode): string {
    return this.tree.getDateTimeIcon(node);
  }

  getDateTimeValue(node: A2uiNode): string {
    return this.tree.getDateTimeValue(node);
  }

  getValue(node: A2uiNode): unknown {
    return this.tree.getValue(node);
  }

  getMinValue(node: A2uiNode): number {
    return this.tree.getMinValue(node);
  }

  getMaxValue(node: A2uiNode): number {
    return this.tree.getMaxValue(node);
  }

  handleSliderChange(node: A2uiNode, event: Event): void {
    const input = event.target as HTMLInputElement;
    const gradientFill = input.parentElement?.querySelector('.gradient-fill') as HTMLElement;
    if (gradientFill) {
      gradientFill.style.setProperty('--inset', 100 - parseInt(input.value, 10) + '%');
    }
  }

  getModalEntryPoint(node: A2uiNode): unknown {
    return this.tree.getModalEntryPoint(node);
  }

  getModalContent(node: A2uiNode): unknown {
    return this.tree.getModalContent(node);
  }

  isModalOpen(node: A2uiNode): boolean {
    return this.modalOpenMap().get(this.getId(node)) ?? false;
  }

  openModal(node: A2uiNode): void {
    const id = this.getId(node);
    this.modalOpenMap.update((m) => {
      const n = new Map(m);
      n.set(id, true);
      return n;
    });
  }

  closeModal(node: A2uiNode): void {
    const id = this.getId(node);
    this.modalOpenMap.update((m) => {
      const n = new Map(m);
      n.set(id, false);
      return n;
    });
  }

  isImageTextRow(node: A2uiNode): boolean {
    return this.tree.isImageTextRow(this.componentsMap(), node);
  }

  getImageFromRow(node: A2uiNode): string {
    return this.tree.getImageFromRow(this.componentsMap(), node);
  }

  getTextFromRow(node: A2uiNode): string {
    return this.tree.getTextFromRow(this.componentsMap(), node);
  }

  getOptions(node: A2uiNode): unknown[] {
    return this.tree.getOptions(node);
  }

  resolveOptionLabel(option: unknown): string {
    return this.tree.resolveOptionLabel(option as Record<string, unknown>);
  }

  /** Suppress DOM for agent-provided controls we handle elsewhere (e.g. rerun). */
  shouldRenderA2uiNode(node: any): boolean {
    return this.getId(node) !== 'rerun-btn';
  }

  isOptionSelected(node: A2uiNode, value: string): boolean {
    const id = this.getId(node);
    const sel = this.selectionsMap();
    if (sel.has(id)) {
      return sel.get(id)!.includes(value);
    }
    const data = this.getData(node);
    const initial = (this.tree.resolveValue(data['selections']) as string[]) || [];
    return initial.includes(value);
  }
}
