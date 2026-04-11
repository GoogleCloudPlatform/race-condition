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
  selector: 'a2ui-notify',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div [class]="'a2ui-'">
      <p>Notification!</p>
    </div>
  `,
  styles: [
    `
      .a2ui-surface {
        width: 100%;
        height: 100%;
      }
    `,
  ],
})
export class A2uiNotifyComponent implements OnChanges {
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
    // this.rootNode = this.findComponentById(rootId);
  }
}
