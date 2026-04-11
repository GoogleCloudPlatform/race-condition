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

import { Component, Input, OnChanges, SimpleChanges, forwardRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { A2uiControllerComponent } from './a2-ui-controller';

@Component({
  selector: 'a2ui-button',
  standalone: true,
  imports: [CommonModule, forwardRef(() => A2uiControllerComponent)],
  template: `
    <button [class]="'a2ui-button'">
      <ng-container *ngFor="let child of getChildren()">
        <a2ui-controller [node]="child" [surface]="surface"></a2ui-controller>
      </ng-container>
    </button>
  `,
  styles: [
    `
      .a2ui-button {
        padding: 8px 16px;
        cursor: pointer;
      }
    `,
  ],
})
export class A2uiButton implements OnChanges {
  @Input() node: any;
  @Input() surface: any;
  rootNode: any = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['surface'] && this.surface) {
      this.updateRootNode();
    }
    if (changes['node']) {
      console.log('Button node changed:', this.node);
    }
  }

  private updateRootNode(): void {
    if (!this.surface || !this.surface.root || !this.surface.components) {
      this.rootNode = null;
      return;
    }

    const rootId = this.surface.root;
    // this.rootNode = this.findComponentById(rootId);
  }

  getChildren(): any[] {
    if (!this.node) return [];
    const data = this.getData(this.node);
    
    let children = data.children || data.child || data.items;
    if (!children && data.slots) {
      children = data.slots.children || data.slots.child || data.slots.items;
    }

    if (!children) return [];
    if (Array.isArray(children)) return children;
    if (children.explicitList) return children.explicitList;
    return [children];
  }

  getData(node: any): any {
    if (!node) return {};
    const type = this.getType(node);
    return node[type] || node.component || node;
  }

  getType(node: any): string {
    if (!node) return '';
    const keys = Object.keys(node);
    const typeKey = keys.find((k) =>
      ['Button', 'Text', 'Image', 'Icon', 'type'].includes(k)
    );
    return typeKey || 'Unknown';
  }
}
