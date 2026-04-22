/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Injectable, NgZone, ChangeDetectorRef, inject } from '@angular/core';
import type { AnimationEvent } from '@angular/animations';
import { TAB_ANIM_PILL_MS } from '../agent-screen.constants';
import { AgentSimulationStatsService } from './agent-simulation-stats.service';

@Injectable()
export class AgentPanelTabExpansionService {
  private readonly ngZone = inject(NgZone);
  private readonly sim = inject(AgentSimulationStatsService);
  private cdr!: ChangeDetectorRef;
  private scheduleAutoResize!: () => void;

  activeTab: 'agent' | 'organizer' | 'log' = 'agent';
  isExpanded = true;
  tabBtnWide = false;
  showTabLabels = true;

  private panelCollapseInProgress = false;
  private showTabLabelsAfterGrowTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private shrinkThenClosePanelTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private pendingTab: 'agent' | 'organizer' | 'log' | null = null;
  private tabSwitchAfterShrinkTimeoutId: ReturnType<typeof setTimeout> | null = null;

  connect(cdr: ChangeDetectorRef, scheduleAutoResize: () => void): void {
    this.cdr = cdr;
    this.scheduleAutoResize = scheduleAutoResize;
  }

  private mark(): void {
    this.cdr.markForCheck();
  }

  clearAnimationTimers(): void {
    if (this.showTabLabelsAfterGrowTimeoutId != null) {
      clearTimeout(this.showTabLabelsAfterGrowTimeoutId);
      this.showTabLabelsAfterGrowTimeoutId = null;
    }
    if (this.shrinkThenClosePanelTimeoutId != null) {
      clearTimeout(this.shrinkThenClosePanelTimeoutId);
      this.shrinkThenClosePanelTimeoutId = null;
    }
    if (this.tabSwitchAfterShrinkTimeoutId != null) {
      clearTimeout(this.tabSwitchAfterShrinkTimeoutId);
      this.tabSwitchAfterShrinkTimeoutId = null;
    }
  }

  onRouteIntroComplete(): void {
    this.isExpanded = true;
  }

  setActiveTab(tab: 'agent' | 'organizer' | 'log'): void {
    if (tab === this.activeTab) return;
    if (this.pendingTab === tab) return;

    if (!this.isExpanded) {
      this.pendingTab = null;
      this.activeTab = tab;
      if (tab === 'agent') {
        this.scheduleAutoResize();
      }
      this.mark();
      return;
    }

    if (this.pendingTab !== null) {
      this.pendingTab = tab;
      this.mark();
      return;
    }

    if (!this.showTabLabels) {
      this.switchTabWithoutLabelClose(tab);
      return;
    }

    this.pendingTab = tab;
    this.showTabLabels = false;
    this.mark();
  }

  private switchTabWithoutLabelClose(tab: 'agent' | 'organizer' | 'log'): void {
    this.clearAnimationTimers();
    this.pendingTab = null;
    this.activeTab = tab;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.mark();
    if (tab === 'agent') {
      this.scheduleAutoResize();
    }
    this.scheduleRevealTabLabelsAfterGrow();
  }

  private scheduleRevealTabLabelsAfterGrow(): void {
    if (this.showTabLabelsAfterGrowTimeoutId != null) {
      clearTimeout(this.showTabLabelsAfterGrowTimeoutId);
      this.showTabLabelsAfterGrowTimeoutId = null;
    }
    this.showTabLabelsAfterGrowTimeoutId = setTimeout(() => {
      this.showTabLabelsAfterGrowTimeoutId = null;
      this.ngZone.run(() => {
        this.showTabLabels = true;
        this.mark();
      });
    }, TAB_ANIM_PILL_MS);
  }

  private applyTabOpenAfterSwitch(): void {
    const next = this.pendingTab;
    if (next == null) return;
    this.pendingTab = null;
    this.activeTab = next;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.mark();
    if (next === 'agent') {
      this.scheduleAutoResize();
    }
    this.scheduleRevealTabLabelsAfterGrow();
  }

  expandPanelAfterCollapsed(): void {
    this.clearAnimationTimers();
    this.pendingTab = null;
    this.panelCollapseInProgress = false;
    this.isExpanded = true;
    this.tabBtnWide = true;
    this.showTabLabels = false;
    this.mark();
    this.scheduleRevealTabLabelsAfterGrow();
  }

  private beginPanelCollapse(): void {
    this.clearAnimationTimers();
    this.pendingTab = null;
    if (!this.showTabLabels) {
      this.tabBtnWide = false;
      this.mark();
      this.shrinkThenClosePanelTimeoutId = setTimeout(() => {
        this.shrinkThenClosePanelTimeoutId = null;
        this.ngZone.run(() => {
          this.isExpanded = false;
          this.mark();
        });
      }, TAB_ANIM_PILL_MS);
      return;
    }
    this.panelCollapseInProgress = true;
    this.showTabLabels = false;
    this.mark();
  }

  togglePanelExpanded(): void {
    if (this.sim.isSimulationRunning) {
      this.sim.showSimPanel = true;
      return;
    }
    if (this.isExpanded) {
      this.beginPanelCollapse();
    } else {
      this.expandPanelAfterCollapsed();
    }
  }

  onTabLabelAnimationDone(event: AnimationEvent): void {
    if (event.triggerName !== 'tabLabel' || event.phaseName !== 'done') return;
    if (event.toState !== 'void' || event.fromState === 'void') return;

    if (this.pendingTab !== null) {
      this.tabBtnWide = false;
      this.mark();
      this.tabSwitchAfterShrinkTimeoutId = setTimeout(() => {
        this.tabSwitchAfterShrinkTimeoutId = null;
        this.ngZone.run(() => this.applyTabOpenAfterSwitch());
      }, TAB_ANIM_PILL_MS);
      return;
    }

    if (!this.panelCollapseInProgress) return;
    this.panelCollapseInProgress = false;
    this.tabBtnWide = false;
    this.mark();
    this.shrinkThenClosePanelTimeoutId = setTimeout(() => {
      this.shrinkThenClosePanelTimeoutId = null;
      this.ngZone.run(() => {
        this.isExpanded = false;
        this.mark();
      });
    }, TAB_ANIM_PILL_MS);
  }
}
