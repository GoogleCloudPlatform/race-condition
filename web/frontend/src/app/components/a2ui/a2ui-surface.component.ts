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

import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-a2ui-surface',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div *ngIf="rootNode" class="a2ui-surface">
      <ng-container *ngTemplateOutlet="renderer; context: { node: rootNode }"></ng-container>
    </div>

    <ng-template #renderer let-node="node">
      <div [class]="'a2ui-' + getType(node)" [attr.data-id]="getId(node)">
        <ng-container [ngSwitch]="getType(node)">
          <span *ngSwitchCase="'Text'" [class]="'text-' + getUsageHint(node)">
            {{ getText(node) }}
          </span>

          <img
            *ngSwitchCase="'Image'"
            [src]="getUrl(node)"
            [class]="'image-' + getUsageHint(node)"
          />

          <button
            *ngSwitchCase="'Button'"
            [class.primary]="isPrimary(node)"
            (click)="handleAction(node)"
          >
            <ng-container
              *ngTemplateOutlet="renderer; context: { node: getChild(node) }"
            ></ng-container>
          </button>

          <video *ngSwitchCase="'Video'" [src]="getUrl(node)" controls></video>

          <div
            *ngSwitchCase="'Divider'"
            class="divider"
            [class.horizontal]="getAxis(node) === 'horizontal'"
            [class.vertical]="getAxis(node) === 'vertical'"
          ></div>

          <input
            *ngSwitchCase="'TextField'"
            [type]="getFieldType(node)"
            [placeholder]="getLabel(node)"
            [value]="getText(node)"
          />

          <div class="a2ui-Slider" *ngSwitchCase="'Slider'">
            <div class="slider-track">
              <div class="label">Runner<br />experience</div>

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
        </ng-container>
      </div>
    </ng-template>
  `,
  styles: [
    `
      .a2ui-surface {
        width: 100%;
        height: 100%;
      }

      .a2ui-Card {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        border-radius: 16px;
        padding: 1.5rem;
      }

      .a2ui-Column {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
      }

      .a2ui-Row {
        display: flex;
        flex-direction: row;
        gap: 0.75rem;
        align-items: center;
      }

      .a2ui-List {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
      }

      .a2ui-Text {
        color: #f1f5f9;
        line-height: 1.6;
      }

      .text-h1 {
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
      }

      .text-h2 {
        font-size: 2rem;
        font-weight: 700;
        margin: 0;
      }

      .text-h3 {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0;
      }

      .text-h4 {
        font-size: 1.25rem;
        font-weight: 600;
        margin: 0;
      }

      .text-h5 {
        font-size: 1rem;
        font-weight: 600;
        margin: 0;
      }

      .text-body {
        font-size: 1rem;
        font-weight: 400;
      }

      .text-caption {
        font-size: 0.875rem;
        color: #94a3b8;
      }

      .a2ui-Button button {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white;
        padding: 0.75rem 1.5rem;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        font-weight: 500;
      }

      .a2ui-Button button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
      }

      .a2ui-Button button.primary {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
      }

      .a2ui-Image img {
        max-width: 100%;
        border-radius: 8px;
      }

      .a2ui-Video video {
        max-width: 100%;
        border-radius: 8px;
      }

      /* -- Slider --- */

      .a2ui-Slider {
        width: 100%;

        position: relative;

        height: 63px;
        user-select: none;
      }

      /* The container/track */
      .slider-track {
        position: relative;
        width: 100%;
        height: 100%;
        background-color: #1c1e21;
        border-radius: 20px;
        overflow: hidden;
        display: flex;
        align-items: center;
      }

      /* The moving gradient part */
      .gradient-fill {
        --inset: 50%;
        position: absolute;
        left: 0;
        top: 0;
        height: 100%;
        width: 100%;
        /* Gradient stops based on your image */
        background: linear-gradient(
          to right,
          #00a859 0%,
          /* Emerald Green */ #1877f2 30%,
          /* Bright Blue */ #9361ff 70%,
          /* Soft Purple */ #e94057 100% /* Pink/Red */
        );
        border-radius: 20px;
        pointer-events: none;
        transition: width 0.1s ease-out;

        clip-path: inset(0% var(--inset) 0% 0% round 12px);
      }
      /* 
      .gradient-mask {
        
      } */

      /* The text label "Runner experience" */
      .label {
        mix-blend-mode: difference;
        color: white;
        position: absolute;
        left: 25px;
        font-size: 18px;
        font-weight: 500;

        line-height: 1.2;
        z-index: 2;
        pointer-events: none;
      }

      /* The white vertical line (thumb) */
      .thumb-line {
        position: absolute;
        right: calc(var(--inset) + 30px);

        top: 25%;
        height: 50%;
        width: 3px;
        background-color: white;
        border-radius: 4px;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
      }

      /* The actual invisible input that handles logic */
      input[type='range'] {
        position: absolute;
        width: 100%;
        height: 100%;
        top: 0;
        left: 0;
        opacity: 0; /* Hide the default look */
        cursor: pointer;
        z-index: 10;
        margin: 0;
      }

      /* -- end Slider --- */

      .divider {
        background: rgba(255, 255, 255, 0.1);
      }

      .divider.horizontal {
        width: 100%;
        height: 1px;
        margin: 0.5rem 0;
      }

      .divider.vertical {
        width: 1px;
        height: 100%;
        margin: 0 0.5rem;
      }

      .a2ui-TextField input {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #f1f5f9;
        padding: 0.75rem;
        border-radius: 8px;
        width: 100%;
        font-size: 1rem;
      }

      .a2ui-TextField input:focus {
        outline: none;
        border-color: #3b82f6;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
      }
    `,
  ],
})
export class A2uiSurfaceComponent implements OnChanges {
  @Input() surface: any;
  rootNode: any = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['surface'] && this.surface) {
      this.updateRootNode();
    }
  }

  private updateRootNode(): void {
    if (!this.surface || !this.surface.root || !this.surface.components) {
      this.rootNode = null;
      return;
    }

    const rootId = this.surface.root;
    this.rootNode = this.findComponentById(rootId);
  }

  private findComponentById(id: string): any {
    if (!this.surface.components) return null;

    for (const component of this.surface.components) {
      const found = this.searchComponent(component, id);
      if (found) return found;
    }
    return null;
  }

  private searchComponent(component: any, id: string): any {
    const componentId = this.getId(component);
    console.log('componentId', componentId);
    if (componentId === id) return component;

    const children = this.getChildren(component);
    for (const child of children) {
      const found = this.searchComponent(child, id);
      console.log(child, found);
      if (found) return found;
    }
    return null;
  }

  getType(node: any): string {
    if (!node) return '';

    const keys = Object.keys(node);
    const typeKey = keys.find((k) =>
      [
        'Card',
        'Column',
        'Row',
        'List',
        'Text',
        'Image',
        'Button',
        'Video',
        'Divider',
        'TextField',
        'Icon',
        'Modal',
        'Tabs',
        'Slider',
      ].includes(k),
    );

    return typeKey || 'Unknown';
  }

  getData(node: any): any {
    if (!node) return {};
    const type = this.getType(node);
    return node[type] || node.component || node;
  }

  getId(node: any): string {
    const data = this.getData(node);
    return data.id || '';
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
    return [children];
  }

  getChild(node: any): any {
    const children = this.getChildren(node);
    return children[0] || null;
  }

  getText(node: any): string {
    const data = this.getData(node);
    return data.text || data.label || '';
  }

  getUrl(node: any): string {
    const data = this.getData(node);
    return data.url || data.src || '';
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
    return data.label || '';
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

  getValue(node: any): number {
    const data = this.getData(node);
    return data.value || 0;
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
    console.log('Slider changed:', {
      target: event.target,
      curr: event.currentTarget,
      id: data.id,
      value: input.value,
      node: data,
    });

    const gradientFill = input.parentElement?.querySelector('.gradient-fill') as HTMLElement;
    if (gradientFill) {
      gradientFill.style.setProperty('--inset', 100 - parseInt(input.value) + '%');
    }

    // event.target?.style.setProperty(
  }

  handleAction(node: any): void {
    const data = this.getData(node);
    if (data.action) {
      console.log('Action triggered:', data.action);
    }
  }
}
