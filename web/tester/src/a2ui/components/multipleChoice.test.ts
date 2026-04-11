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

import { describe, it, expect } from "vitest";
import { MultipleChoiceRenderer } from "./multipleChoice";

describe("MultipleChoiceRenderer", () => {
  it("renders options", () => {
    const el = MultipleChoiceRenderer({ 
      options: [{ value: 'v1', label: 'Option 1' }],
      selections: [] 
    })
    expect(el.textContent).toContain('Option 1')
  })

  it("marks selections as active with premium styling", () => {
    const el = MultipleChoiceRenderer({ 
      options: [{ value: 'v1', label: 'Opt 1' }],
      selections: ['v1']
    })
    const btn = el.querySelector('button')
    // Check for premium active classes
    expect(btn?.className).toContain('bg-indigo-600/20')
    expect(btn?.className).toContain('border-indigo-500')
    expect(btn?.innerHTML).toContain('check_circle')
  })
});
