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

export interface LogBufferOptions {
  container: () => HTMLElement | null;
  maxEntries?: number;
  evictionBatch?: number;
  onEvict?: (dropped: number) => void;
  onScroll?: () => void;
}

export interface LogBuffer {
  append(el: HTMLElement): void;
  droppedCount(): number;
  reset(): void;
}

const DEFAULT_MAX_ENTRIES = 500;
const DEFAULT_EVICTION_BATCH = 100;

export function createLogBuffer(opts: LogBufferOptions): LogBuffer {
  const maxEntries = opts.maxEntries ?? DEFAULT_MAX_ENTRIES;
  const evictionBatch = opts.evictionBatch ?? DEFAULT_EVICTION_BATCH;
  let dropped = 0;
  let queue: HTMLElement[] = [];
  let rafId: number | null = null;

  function flush(): void {
    rafId = null;

    const pending = queue;
    queue = [];

    if (pending.length === 0) return;

    const container = opts.container();
    if (!container) return;

    // Batch all queued elements into a single DocumentFragment (one reflow)
    const fragment = document.createDocumentFragment();
    for (const el of pending) {
      fragment.appendChild(el);
    }
    container.appendChild(fragment);

    // Evict oldest entries if over cap
    if (container.children.length > maxEntries) {
      const toRemove = Math.min(evictionBatch, container.children.length);
      for (let i = 0; i < toRemove; i++) {
        container.removeChild(container.children[0]);
      }
      dropped += toRemove;
      opts.onEvict?.(dropped);
    }

    opts.onScroll?.();
  }

  function append(el: HTMLElement): void {
    queue.push(el);
    if (rafId === null) {
      rafId = requestAnimationFrame(flush);
    }
  }

  function droppedCount(): number {
    return dropped;
  }

  function reset(): void {
    dropped = 0;
    queue = [];
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  return { append, droppedCount, reset };
}
