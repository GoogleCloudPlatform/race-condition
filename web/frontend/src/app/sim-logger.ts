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

class SimLogger {
  private entries: string[] = [];
  private t0 = 0;

  clear(): void {
    this.entries = [];
    this.t0 = performance.now();
  }

  log(category: string, id: string, msg: string): void {
    if (!this.t0) this.t0 = performance.now();
    const t = ((performance.now() - this.t0) / 1000).toFixed(3);
    const short = id.length > 20 && !id.includes(' ') ? id.slice(-8) : id;
    this.entries.push(`[${t}s] [${category}] ${short}: ${msg}`);
  }

  copyToClipboard(): Promise<void> {
    if (!this.entries.length) return Promise.resolve();
    return navigator.clipboard.writeText(this.entries.join('\n'));
  }

  get size(): number { return this.entries.length; }
}

export const simLog = new SimLogger();
