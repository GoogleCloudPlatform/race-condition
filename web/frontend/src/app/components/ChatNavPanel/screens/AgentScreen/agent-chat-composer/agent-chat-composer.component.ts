/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-agent-chat-composer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule],
  templateUrl: './agent-chat-composer.component.html',
  styleUrls: ['./agent-chat-composer.component.scss'],
})
export class AgentChatComposerComponent implements AfterViewInit, OnChanges {
  @ViewChild('chatTextArea', { read: ElementRef }) textAreaRef!: ElementRef<HTMLTextAreaElement>;

  @Input({ required: true }) text = '';
  @Output() textChange = new EventEmitter<string>();

  @Input({ required: true }) placeholder = '';
  @Input({ required: true }) isAgentWorking = false;
  @Input({ required: true }) canSend = false;
  @Input({ required: true }) isSecuringAgent = false;

  @Output() send = new EventEmitter<void>();

  ngAfterViewInit(): void {
    this.scheduleAutoResize();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['text']) {
      this.scheduleAutoResize();
    }
  }

  private scheduleAutoResize(): void {
    setTimeout(() => this.autoResize(), 0);
  }

  onInput(value: string): void {
    this.textChange.emit(value);
    this.autoResize();
  }

  onChatEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (ke.shiftKey) return;
    ke.preventDefault();
    this.send.emit();
  }

  autoResize(): void {
    const textarea = this.textAreaRef?.nativeElement;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }

  resetHeight(): void {
    const textarea = this.textAreaRef?.nativeElement;
    if (textarea) textarea.style.height = 'auto';
  }
}
