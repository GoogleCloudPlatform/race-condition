/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import type { AgentScreenHost } from '../agent-screen-host.model';

@Component({
  selector: 'app-agent-settings-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule],
  templateUrl: './agent-settings-menu.component.html',
  styleUrls: ['./agent-settings-menu.component.scss'],
})
export class AgentSettingsMenuComponent {
  @Input({ required: true }) host!: AgentScreenHost;

  /** Mirrors `host.isExpanded` so OnPush sees updates (the `host` reference does not change). */
  @Input({ required: true }) panelExpanded!: boolean;
}
