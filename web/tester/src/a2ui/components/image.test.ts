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

/**
 * A2UI Image Component Test - v0.8.0
 */

import { describe, it, expect } from 'vitest'
import { ImageRenderer } from './image'

describe('ImageRenderer', () => {
  it('renders an image element with correct src', () => {
    const el = ImageRenderer({ url: 'http://example.com/test.png' })
    const img = el.querySelector('img')
    
    expect(img).toBeTruthy()
    expect(img?.getAttribute('src')).toBe('http://example.com/test.png')
  })

  it('scales according to avatar usageHint', () => {
    const el = ImageRenderer({ url: 'test.png', usageHint: 'avatar' })
    expect(el.className).toContain('w-12')
    expect(el.className).toContain('rounded-full')
  })

  it('scales according to smallFeature usageHint', () => {
    const el = ImageRenderer({ url: 'test.png', usageHint: 'smallFeature' })
    expect(el.className).toContain('w-24')
    expect(el.className).toContain('rounded-2xl')
  })
})
