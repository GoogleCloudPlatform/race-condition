/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Component, Input, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MarkdownPipe } from 'ngx-markdown';
import { A2uiControllerComponent } from '../../../../a2ui/a2-ui-controller.component';
import type { DisplayItem } from '../agent-screen.types';
import type { AgentScreenHost } from '../agent-screen-host.model';

@Component({
  selector: 'app-agent-chat-thread',
  standalone: true,
  imports: [CommonModule, MarkdownPipe, A2uiControllerComponent],
  templateUrl: './agent-chat-thread.component.html',
  styleUrls: ['./agent-chat-thread.component.scss'],
})
export class AgentChatThreadComponent {
  @Input({ required: true }) host!: AgentScreenHost;

  @ViewChild('chatScroll', { read: ElementRef }) chatScrollRef!: ElementRef<HTMLDivElement>;

  trackByDisplayItem = (i: number, item: DisplayItem): string =>
    this.host.chatDisplay.trackByDisplayItem(i, item);

  getScrollNative(): HTMLDivElement {
    return this.chatScrollRef.nativeElement;
  }
}
