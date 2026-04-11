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

import { describe, it, expect } from 'vitest';
import { renderA2UI, resolveValue } from './index';

describe('A2UI Core Rendering (v0.8.0 Strict)', () => {
  it('should resolve literal string wrappers', () => {
    expect(resolveValue({ literalString: 'hello' })).toBe('hello');
    expect(resolveValue('hello')).toBe('hello');
  });

  it('should resolve literal number wrappers', () => {
    expect(resolveValue({ literalNumber: 42 })).toBe(42);
    expect(resolveValue(42)).toBe(42);
  });

  it('should render a strictly compliant Text component', () => {
    const part = {
      id: 'c1',
      component: {
        Text: {
          text: { literalString: 'Hello World' },
          usageHint: 'h1'
        }
      }
    };
    const el = renderA2UI(part);
    expect(el.tagName).toBe('SPAN');
    expect(el.textContent).toBe('Hello World');
    expect(el.getAttribute('data-a2ui-type')).toBe('Text');
    expect(el.getAttribute('data-a2ui-id')).toBe('c1');
    expect(el.className).toContain('text-2xl');
  });

  it('should render a Column with children resolved by ID', () => {
    const part = {
      surfaceUpdate: {
        surfaceId: 's1',
        components: [
          {
            id: 't1',
            component: { Text: { text: { literalString: 'Item 1' } } }
          },
          {
            id: 'col1',
            component: { 
              Column: { 
                children: { explicitList: ['t1'] }
              } 
            }
          }
        ]
      }
    };
    const el = renderA2UI(part);
    expect(el.classList.contains('a2ui-column')).toBe(true);
    expect(el.children.length).toBe(1);
    expect(el.children[0].textContent).toBe('Item 1');
  });

  it('should handle missing component IDs gracefully', () => {
    const part = {
      id: 'col1',
      component: { 
        Column: { 
          children: { explicitList: ['missing-id'] }
        } 
      }
    };
    const el = renderA2UI(part, { components: {} });
    expect(el.textContent).toContain('Missing Component ID');
  });

  it('should render a MessageBox component', () => {
    const part = {
      id: 'mb1',
      component: {
        MessageBox: {
          speaker: { literalString: 'Test Speaker' },
          text: { literalString: 'Test Message Content' }
        }
      }
    };
    const el = renderA2UI(part);
    expect(el.getAttribute('data-a2ui-type')).toBe('MessageBox');
    expect(el.textContent).toContain('Test Speaker');
    expect(el.textContent).toContain('Test Message Content');
  });

  it('should handle beginRendering message', () => {
    const part = {
      beginRendering: {
        root: 'root1'
      }
    };
    const el = renderA2UI(part);
    expect(el.getAttribute('data-a2ui-type')).toBe('beginRendering');
    expect(el.textContent).toContain('Initializing Surface');
  });

  it('should handle dataModelUpdate message', () => {
    const part = {
      dataModelUpdate: {
        path: '/user/name',
        contents: 'Casey'
      }
    };
    const el = renderA2UI(part);
    expect(el.getAttribute('data-a2ui-type')).toBe('dataModelUpdate');
    expect(el.textContent).toContain('Data Model Update');
  });

  it('should return error for non-compliant structures', () => {
    const part = { type: 'Legacy', props: {} };
    const el = renderA2UI(part);
    expect(el.classList.contains('a2ui-error')).toBe(true);
  });
});
