/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Injectable, NgZone, ChangeDetectorRef, inject } from '@angular/core';
import {
  HARDCODED_SIM_DISTANCE_INTEGRATOR,
  HARDCODED_SIM_PROGRESS_WALL_MS,
  MARATHON_DISTANCE_MI,
} from '../../../../../runner-sim-constants';
import { agentGateway } from '../../../../../agent-gateway-updates';
import { FINISH_UI_PROGRESS_T } from '../agent-screen.constants';
import { formatPaceFromNormalizedAvgVelocity } from '../agent-screen-formatters';

@Injectable()
export class AgentSimulationStatsService {
  private ngZone = inject(NgZone);
  private cdr!: ChangeDetectorRef;

  showSimPanel = false;
  isSimulationRunning = false;
  simulationProgress = 0;
  private simProgressStartMs = 0;
  private simProgressRafId: number | null = null;

  averageDistance = 0;
  numberOfFinishers = 0;
  numberOfActiveRunners = 0;
  averagePace = '0:00';
  isFollowingLeader = false;

  readonly runnersFinishedAwaitingHud = new Set<string>();
  private readonly runnerCourseProgressByGuid = new Map<string, number>();

  connect(cdr: ChangeDetectorRef): void {
    this.cdr = cdr;
    agentGateway.setUiNumberOfFinishersGetter(() => this.numberOfFinishers);
  }

  dispose(): void {
    agentGateway.setUiNumberOfFinishersGetter(null);
    if (this.simProgressRafId != null) {
      cancelAnimationFrame(this.simProgressRafId);
      this.simProgressRafId = null;
    }
  }

  private mark(): void {
    this.cdr.markForCheck();
  }

  onFollowLeader(): void {
    this.isFollowingLeader = true;
    window.dispatchEvent(new CustomEvent('hud:followLeader'));
  }

  onFollowRandomRunner(): void {
    this.isFollowingLeader = false;
    window.dispatchEvent(new CustomEvent('hud:followRandomRunner'));
  }

  readonly onFollowStopped = (): void => {
    this.ngZone.run(() => {
      this.isFollowingLeader = false;
      this.mark();
    });
  };

  readonly onHudUpdateSimRunnerForFinishers = (e: Event): void => {
    const d = (e as CustomEvent).detail as {
      guid?: string;
      progress?: number;
    };

    if (!d.guid) return;
    if (typeof d.progress !== 'number' || !Number.isFinite(d.progress)) return;

    this.ngZone.run(() => {
      const clamped = Math.min(1, Math.max(0, d.progress!));
      this.runnerCourseProgressByGuid.set(d.guid!, clamped);

      if (this.runnerCourseProgressByGuid.size > 0) {
        let sumT = 0;
        for (const t of this.runnerCourseProgressByGuid.values()) {
          sumT += t;
        }
        const avgT = sumT / this.runnerCourseProgressByGuid.size;
        this.averageDistance = Math.round(avgT * MARATHON_DISTANCE_MI * 10) / 10;
      }

      if (d.progress! >= FINISH_UI_PROGRESS_T) {
        if (!this.runnersFinishedAwaitingHud.has(d.guid!)) {
          this.runnersFinishedAwaitingHud.add(d.guid!);
          this.numberOfFinishers++;
        }
      }

      this.mark();
    });
  };

  readonly onFirstBatchAvgVelocity = (e: Event): void => {
    const d = (e as CustomEvent).detail as { avgVelocity?: number };
    const avg = d?.avgVelocity;
    if (avg === undefined || avg <= 0) return;
    this.ngZone.run(() => {
      this.averagePace = formatPaceFromNormalizedAvgVelocity(avg);
      this.mark();
    });
  };

  handleTickUpdate(d: Record<string, unknown>): void {
    if (this.runnerCourseProgressByGuid.size === 0) {
      const rawMi = Number(d['avg_distance']);
      this.averageDistance = Number.isFinite(rawMi) ? Math.round(rawMi * 10) / 10 : 0;
    }
    this.numberOfActiveRunners = Number(d['runners_reporting']) || 0;
    this.averagePace = formatPaceFromNormalizedAvgVelocity(Number(d['avg_velocity']) || 0);
    this.mark();
  }

  private runProgressAnimation(): void {
    const elapsed = Date.now() - this.simProgressStartMs;
    const rawPct = Math.min(100, (elapsed / HARDCODED_SIM_PROGRESS_WALL_MS) * 100);
    this.simulationProgress = Math.round(rawPct * 100) / 100;

    this.mark();
    if (this.simulationProgress < 100) {
      this.simProgressRafId = requestAnimationFrame(() => this.runProgressAnimation());
    } else {
      this.simProgressRafId = null;
    }
  }

  handleRaceStarted(): void {
    window.dispatchEvent(
      new CustomEvent('sim:raceStarted', {
        detail: { speedMultiplier: 1, simDistanceIntegrator: HARDCODED_SIM_DISTANCE_INTEGRATOR },
      }),
    );

    this.showSimPanel = true;
    this.isSimulationRunning = true;
    this.simulationProgress = 0;
    this.simProgressStartMs = Date.now();
    if (this.simProgressRafId != null) {
      cancelAnimationFrame(this.simProgressRafId);
      this.simProgressRafId = null;
    }
    this.simProgressRafId = requestAnimationFrame(() => this.runProgressAnimation());
    this.mark();
  }

  readonly onSimRaceStarted = (): void => {
    this.ngZone.run(() => {
      this.resetSimulationStatistics();
      this.showSimPanel = true;
      this.isSimulationRunning = true;
      this.mark();
    });
  };

  onSimFinished = (): void => {
    this.showSimPanel = false;
    this.isSimulationRunning = false;
  };

  resetSimulationStatistics(): void {
    this.simulationProgress = 0;
    this.averageDistance = 0;
    this.numberOfFinishers = 0;
    this.runnersFinishedAwaitingHud.clear();
    this.runnerCourseProgressByGuid.clear();
    this.averagePace = '0:00';

    if (this.simProgressRafId != null) {
      cancelAnimationFrame(this.simProgressRafId);
      this.simProgressRafId = null;
    }
  }
}
