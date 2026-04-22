/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Component, Input, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import type { AgentScreenHost } from '../agent-screen-host.model';
import { AgentChatThreadComponent } from '../agent-chat-thread/agent-chat-thread.component';
import { AgentChatComposerComponent } from '../agent-chat-composer/agent-chat-composer.component';

@Component({
  selector: 'app-agent-chat-panel',
  standalone: true,
  imports: [CommonModule, AgentChatThreadComponent, AgentChatComposerComponent],
  templateUrl: './agent-chat-panel.component.html',
  styleUrls: ['./agent-chat-panel.component.scss'],
})
export class AgentChatPanelComponent {
  @Input({ required: true }) host!: AgentScreenHost;

  @ViewChild(AgentChatThreadComponent) private chatThread?: AgentChatThreadComponent;

  getChatScrollNative(): HTMLDivElement | undefined {
    return this.chatThread?.getScrollNative();
  }

  scrollChatToBottom(): void {
    const el = this.chatThread?.getScrollNative();
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }

  onTextChange(value: string): void {
    this.host.chatInput = value;
    this.host.cdr.markForCheck();
  }
}
