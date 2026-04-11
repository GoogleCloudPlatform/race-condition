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

import { Injectable, OnDestroy, signal } from '@angular/core';
import { DEMO_HOTKEYS, DEMO_IDS, DemoId } from '../../../constants';

@Injectable({ providedIn: 'root' })
export class DemoService implements OnDestroy {
  readonly activeDemo = signal<DemoId>('CI');
  readonly showAlternativePanels = signal<boolean>(false);
  readonly reset = signal<number>(0);

  private onKeyDown = (e: KeyboardEvent) => {
    if (e.ctrlKey && DEMO_HOTKEYS.includes(e.key)) {
      if (e.key === 'd') {
        this.showAlternativePanels.set(!this.showAlternativePanels());
        return;
      }
      if (
        e.key === 'r' ||
        DEMO_IDS[DEMO_HOTKEYS.findIndex((key) => key === e.key)] === this.activeDemo()
      ) {
        this.reset.update((n) => n + 1);
        return;
      }
      this.activeDemo.set(DEMO_IDS[DEMO_HOTKEYS.findIndex((key) => key === e.key)]);
    }
  };

  constructor() {
    window.addEventListener('keydown', this.onKeyDown);
  }

  ngOnDestroy() {
    window.removeEventListener('keydown', this.onKeyDown);
  }

  select(id: DemoId) {
    this.activeDemo.set(id);
  }
}
