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
 * A2UI Video Component Test - v0.8.0
 */

import { describe, it, expect } from 'vitest'
import { VideoRenderer } from './video'

describe('VideoRenderer', () => {
  it('renders a video element with correct src', () => {
    const el = VideoRenderer({ url: 'http://example.com/video.mp4' })
    const video = el.querySelector('video')
    
    expect(video).toBeTruthy()
    expect(video?.getAttribute('src')).toBe('http://example.com/video.mp4')
  })

  it('respects the autoplay property', () => {
    const autoplaceEl = VideoRenderer({ url: 'test.mp4', autoplay: true })
    expect(autoplaceEl.querySelector('video')?.hasAttribute('autoplay')).toBe(true)

    const manualEl = VideoRenderer({ url: 'test.mp4', autoplay: false })
    expect(manualEl.querySelector('video')?.hasAttribute('autoplay')).toBe(false)
  })

  it('includes a "Native Stream" badge', () => {
    const el = VideoRenderer({ url: 'test.mp4' })
    expect(el.textContent).toContain('Native Stream')
  })
})
