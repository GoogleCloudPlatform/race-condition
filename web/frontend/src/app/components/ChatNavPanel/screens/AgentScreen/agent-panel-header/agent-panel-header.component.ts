/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Component, ChangeDetectionStrategy, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { AgentScreenHost } from '../agent-screen-host.model';
import { AgentTabStripComponent } from '../agent-tab-strip/agent-tab-strip.component';
import { AgentSettingsMenuComponent } from '../agent-settings-menu/agent-settings-menu.component';

@Component({
  selector: 'app-agent-panel-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, AgentTabStripComponent, AgentSettingsMenuComponent],
  templateUrl: './agent-panel-header.component.html',
  styleUrls: ['./agent-panel-header.component.scss'],
})
export class AgentPanelHeaderComponent {
  @Input({ required: true }) host!: AgentScreenHost;
  @Input({ required: true }) panelExpanded!: boolean;
  @Input({ required: true }) activeTab!: 'agent' | 'organizer' | 'log';
  @Input({ required: true }) tabBtnWide!: boolean;
  @Input({ required: true }) showTabLabels!: boolean;
  @Input({ required: true }) isAgentWorking!: boolean;

  @Output() expandToggle = new EventEmitter<void>();
}
