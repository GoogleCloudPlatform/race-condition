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

import { describe, it, expect, beforeEach, vi } from "vitest";
import { createLogBuffer } from "./logBuffer";

/** Helper: wait for the next rAF flush. */
const flushRAF = () =>
  new Promise<void>((r) => requestAnimationFrame(() => r()));

describe("createLogBuffer (rAF-batched)", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
  });

  it("queues elements and flushes on rAF", async () => {
    const buf = createLogBuffer({ container: () => container });
    const el1 = document.createElement("div");
    const el2 = document.createElement("div");

    buf.append(el1);
    buf.append(el2);

    // Before rAF fires, container should be empty
    expect(container.children.length).toBe(0);

    await flushRAF();

    // After rAF, both elements should be in the container
    expect(container.children.length).toBe(2);
    expect(container.children[0]).toBe(el1);
    expect(container.children[1]).toBe(el2);
  });

  it("evicts a batch when flushing exceeds maxEntries", async () => {
    const onEvict = vi.fn();
    const buf = createLogBuffer({
      container: () => container,
      maxEntries: 5,
      evictionBatch: 3,
      onEvict,
    });

    for (let i = 0; i < 8; i++) {
      const el = document.createElement("div");
      el.textContent = `msg-${i}`;
      buf.append(el);
    }

    await flushRAF();

    // 8 appended, cap is 5, so evict 3 oldest => 5 remain
    expect(container.children.length).toBe(5);
    expect(onEvict).toHaveBeenCalledWith(3);
  });

  it("calls onScroll callback once per flush", async () => {
    const onScroll = vi.fn();
    const buf = createLogBuffer({
      container: () => container,
      onScroll,
    });

    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));

    await flushRAF();

    expect(onScroll).toHaveBeenCalledTimes(1);
  });

  it("handles null container gracefully", async () => {
    const buf = createLogBuffer({ container: () => null });
    const el = document.createElement("div");

    // Should not throw
    buf.append(el);
    await flushRAF();

    expect(buf.droppedCount()).toBe(0);
  });

  it("reset clears dropped count and pending queue", async () => {
    const buf = createLogBuffer({
      container: () => container,
      maxEntries: 3,
      evictionBatch: 2,
    });

    // Fill and evict
    for (let i = 0; i < 5; i++) {
      buf.append(document.createElement("div"));
    }
    await flushRAF();
    expect(buf.droppedCount()).toBe(2);

    // Queue elements but reset before they flush
    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));
    buf.reset();

    expect(buf.droppedCount()).toBe(0);

    // The pending rAF was cancelled, so nothing new should arrive
    const countBefore = container.children.length;
    await flushRAF();
    expect(container.children.length).toBe(countBefore);
  });

  it("coalesces multiple frames correctly", async () => {
    const onScroll = vi.fn();
    const buf = createLogBuffer({
      container: () => container,
      onScroll,
    });

    // First batch
    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));
    await flushRAF();
    expect(container.children.length).toBe(2);
    expect(onScroll).toHaveBeenCalledTimes(1);

    // Second batch
    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));
    buf.append(document.createElement("div"));
    await flushRAF();
    expect(container.children.length).toBe(5);
    expect(onScroll).toHaveBeenCalledTimes(2);
  });

  it("eviction removes oldest entries (first children)", async () => {
    const buf = createLogBuffer({
      container: () => container,
      maxEntries: 3,
      evictionBatch: 2,
    });

    for (let i = 0; i < 5; i++) {
      const el = document.createElement("div");
      el.textContent = `msg-${i}`;
      buf.append(el);
    }

    await flushRAF();

    // 5 appended, cap 3, evict 2 oldest => msg-2, msg-3, msg-4 remain
    expect(container.children.length).toBe(3);
    expect(container.children[0].textContent).toBe("msg-2");
    expect(container.children[1].textContent).toBe("msg-3");
    expect(container.children[2].textContent).toBe("msg-4");
  });

  it("onEvict receives cumulative count across flushes", async () => {
    const onEvict = vi.fn();
    const buf = createLogBuffer({
      container: () => container,
      maxEntries: 3,
      evictionBatch: 2,
      onEvict,
    });

    // First flush: 5 items, evict 2, dropped=2
    for (let i = 0; i < 5; i++) buf.append(document.createElement("div"));
    await flushRAF();
    expect(onEvict).toHaveBeenLastCalledWith(2);

    // Second flush: add 3 more => 4 total in DOM, evict 2, dropped=4
    for (let i = 0; i < 3; i++) buf.append(document.createElement("div"));
    await flushRAF();
    expect(onEvict).toHaveBeenLastCalledWith(4);
    expect(buf.droppedCount()).toBe(4);
  });

  it("handles evictionBatch larger than maxEntries", async () => {
    const buf = createLogBuffer({
      container: () => container,
      maxEntries: 2,
      evictionBatch: 10,
    });

    for (let i = 0; i < 3; i++) {
      buf.append(document.createElement("div"));
    }

    await flushRAF();

    // evictionBatch (10) clamped to container.children.length (3) => all removed
    expect(container.children.length).toBe(0);
    expect(buf.droppedCount()).toBe(3);
  });
});
