/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { trigger, style, transition, animate, type AnimationEvent } from '@angular/animations';
import { SpinnerComponent } from '../../../../Spinner/spinner.component';
import type { AgentScreenHost } from '../agent-screen-host.model';
import { TAB_ANIM_PILL_MS } from '../agent-screen.constants';

const TAB_ANIM_LABEL_LEAVE_MS = Math.round(TAB_ANIM_PILL_MS * 0.8);

@Component({
  selector: 'app-agent-tab-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, SpinnerComponent],
  templateUrl: './agent-tab-strip.component.html',
  styleUrls: ['./agent-tab-strip.component.scss'],
  animations: [
    trigger('tabLabel', [
      transition(':enter', [
        style({ opacity: 0, transform: 'translateY(-8px)' }),
        animate(
          `${TAB_ANIM_PILL_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`,
          style({ opacity: 1, transform: 'translateY(0)' }),
        ),
      ]),
      transition(':leave', [
        animate(
          `${TAB_ANIM_LABEL_LEAVE_MS}ms cubic-bezier(0.4, 0, 1, 1)`,
          style({ opacity: 0, transform: 'translateY(-8px)' }),
        ),
      ]),
    ]),
  ],
})
export class AgentTabStripComponent {
  @Input({ required: true }) host!: AgentScreenHost;

  /** Primitives mirrored from `host` so OnPush sees updates (the `host` reference does not change). */
  @Input({ required: true }) panelExpanded!: boolean;
  @Input({ required: true }) activeTab!: 'agent' | 'organizer' | 'log';
  @Input({ required: true }) tabBtnWide!: boolean;
  @Input({ required: true }) showTabLabels!: boolean;
  @Input({ required: true }) isAgentWorking!: boolean;
}
