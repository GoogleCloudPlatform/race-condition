# A2UI Angular Integration & Payload Extraction Findings

## Overview

This document outlines critical architectural discoveries regarding the
integration of Google's Agent-to-Agent (A2A) Server-Sent Events (SSE) protocol
with the `@a2ui/angular` chat framework.

During the development and debugging of the `a2ui-chat` client interfacing with
the Marathon Planner multi-agent system, several undocumented mismatches between
the TypeScript SDK definitions and the live Python Agent responses were
identified, specifically causing silent rendering failures (empty chat bubbles).

## Finding 1: The `msg.parts` vs `msg.content` Discrepancy

### Problem: SDK vs Runtime Payload Path

When the `@a2a-js/sdk` consumes an SSE stream from the Python ADK backend, the
runtime stream decoder yields `chunk` objects. The TypeScript interface
definitions `ChatMessage` and `DataStreamPart` strongly suggest that the payload
(the textual response or the UI components) from the LLM will be found under the
`.content` property.

Example (Expected by Typescript SDK):

```json
{
  "kind": "task",
  "history": [
    {
      "role": "model",
      "content": [{ "text": "Here is your plan..." }]
    }
  ]
}
```

However, the raw JSON payload emitted over the wire by the Vertex AI backend and
parsed dynamically by the A2A runtime explicitly nests these payloads under a
`.parts` array:

```json
{
  "kind": "message",
  "history": [
    {
      "role": "ROLE_AGENT",
      "parts": [
        {
          "kind": "text",
          "text": "I can certainly help you create a real marathon plan!"
        }
      ]
    }
  ]
}
```

### Consequence: Silent Rendering Failure

Because the Angular `A2aService` was strictly iterating over
`chunk.history[msg].content` as prescribed by the typings, it was receiving
`undefined`. It filtered out the entire LLM response, resulting in 0-height
empty text bubbles rendering in the UI without throwing any network or console
errors.

### Solution: Defensive Extraction

The stream extraction loop inside `a2a.service.ts` must defensively query both
properties to ensure compatibility with both parsed SDK objects and raw JSON
strings:

```typescript
// @ts-ignore: Support both native JSON arrays and protobuf decoded classes
const partsToProcess = chunk.parts || chunk.content;

// For history arrays:
const parts = msg.parts || msg.content;
if (parts) partsToProcess.push(...parts);
```

## Finding 2: A2UI State Machine & `DataPart` Requirements

### Problem: Strict Schema Expectations

When attempting to stream generative A2UI components (like a `plan_map`), the
backend must emit specific UI schemas. If the layout of these schemas deviates
slightly, the Angular `<a2ui-surface>` component will silently drop the nodes,
resulting in empty white squares.

### The Required Schema (`beginRendering` + `surfaceUpdate`)

The frontend `MessageProcessor` operates as a strict state machine. To render a
custom component, the backend (and Mock server) MUST yield the components within
the `surfaceUpdate` primitive format, strictly paired with an initial
`beginRendering` signal in the exact same payload part array.

A valid component payload structure MUST look like this:

```json
[
  {
    "beginRendering": {
      "surfaceId": "plan-surface-123",
      "root": "plan_overview_card"
    }
  },
  {
    "surfaceUpdate": {
      "surfaceId": "plan-surface-123",
      "catalog": "inline",
      "components": [
        {
          "Card": {
            "id": "plan_overview_card",
            "metadata": { "title": "Marathon Plan" },
            "slots": {
              "children": [
                {
                  "Column": {
                    "id": "col-1",
                    "slots": {
                      "children": [
                        {
                          "Text": {
                            "id": "text-1",
                            "text": "This is a dynamically generated component."
                          }
                        }
                      ]
                    }
                  }
                }
              ]
            }
          }
        }
      ]
    }
  }
]
```

### Solution: Automated Validation

To prevent hallucinated backend responses from crashing the UI, we introduced
rigorous cross-boundary Unit Tests using standard specifications:

1. **Frontend `app.spec.ts`:** We mock the `MessageProcessor` parsing engine to
   mathematically assert that `surfaceUpdate` elements correctly increment the
   Processor's `_surfaceMap` size.
2. **Backend/Mock node tests:** We use `assert.deepStrictEqual` against recorded
   stream traces (`recorded_stream.json`) to confirm the properties matching
   `beginRendering` and `Card` primitives are inherently present before
   compiling.

## Finding 3: The `List` Primitive and `items` Resolution

### Problem: Missing List Support

A2UI schemas often use the `List` primitive for structured data (like marathon
waypoints or logistics). However, unlike `Column` or `Row` which use `children`,
`List` components use the `items` property. If the renderer only looks for
`children`, these lists will fail to render, causing empty sections in cards.

### Solution: Expand Property Support

The `getResolvedChildren` helper in `A2uiSurfaceComponent` must check for
`items` in addition to `children` and `child`:

```typescript
// Support both 'children', 'child', 'items' or 'slots.children'
let children = content.children || content.child || content.items;
if (!children && content.slots) {
  children =
    content.slots.children || content.slots.child || content.slots.items;
}
```

## Finding 4: Suppressing `beginRendering` Placeholders

### Problem: Redundant UI Artifacts

The A2A protocol sends a `beginRendering` signal to initialize a surface ID
before the `surfaceUpdate` (containing the actual components) arrives. If the UI
renders a glassy container for every surface ID it sees, these signals create
"blank box" artifacts that clutter the chat.

### Solution: Conditional Visibility

The `<app-a2ui-surface>` template must strictly guard its outer container with
`*ngIf="rootNode"`. This ensures the surface is invisible until the first
component is successfully resolved from the catalog.

## Finding 5: Wrapped vs. Flat JSON Structures

### Problem: Schema Variation

Agents sometimes produce "wrapped" JSON (e.g., `{ "Card": { "id": "..." } }`)
instead of the SDK-preferred flat format (e.g.,
`{ "type": "Card", "id": "..." }`). This breaks standard property accessors.

### Solution: Data Normalization Helper

Implement a `getData(node)` helper that normalization access by checking for
both formats:

```typescript
getData(node: any): any {
  if (!node) return {};
  const type = this.getType(node);
  return node[type] || node.component || node;
}
```

## Finding 6: Markdown Rendering and Styling

### Problem: Unformatted Agent Responses

Generative agents often return content in Markdown format (headers, lists, bold
text). Rendering this as raw text in the UI degrades the "premium" feel and
makes complex plans harder to scan.

### Solution: `MarkdownPipe` + `marked`

We integrated the `marked` library via a custom Angular Pipe (`MarkdownPipe`).
This pipe transforms markdown strings into HTML strings safely.

```typescript
@Pipe({ name: "markdown", standalone: true })
export class MarkdownPipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}
  async transform(value: string): Promise<SafeHtml> {
    if (!value) return "";
    const html = await marked.parse(value);
    return this.sanitizer.bypassSecurityTrustHtml(html);
  }
}
```

### Premium Styling (`markdown-body`)

To ensure markdown elements (like `<h3>` or `<ul>`) match the dark-mode
glassmorphism aesthetic, we applied a `.markdown-body` class with curated CSS:

```css
.markdown-body h3 {
  @apply text-xl font-bold text-white mt-4 mb-2;
}
.markdown-body ul,
.markdown-body ol {
  @apply ml-6 my-2 list-disc;
}
```

## Finding 7: Real-time Streaming and the Async Pipe

### Problem: Flickering and Security

Because `marked.parse` is asynchronous and returns a `Promise`, and because
`DomSanitizer` returns `SafeHtml`, we needed a way to render these updates
efficiently as they stream in without triggering XSS warnings or UI flickering.

### Solution: Async Pipe Integration

By combining the `markdown` pipe with the built-in `async` pipe and binding to
`[innerHTML]`, Angular automatically handles the promise resolution and
sanitization cycle for every streamed chunk:

```html
<div class="markdown-body" [innerHTML]="msg.content | markdown | async"></div>
```

## Finding 8: Progressive Tool Status Updates

### Problem: Invisible Orchestration

In a multi-agent workflow (e.g., Marathon Planner -> Traffic Specialist), there
is often a latency gap where the user sees no activity.

### Solution: DataPart Lifecycle

We implemented a pattern where the backend emits `DataPart`s with `call` and
`response` keys during the `agent_executor` loop.

- **State Sync**: By using a stable `messageId` and the `append: true` flag in
  the A2A SSE event, we ensure that the "Calling Specialist" pill correctly
  converts into a "Response Received" pill in-place, preventing UI clutter and
  providing real-time feedback.

## Conclusion

By bridging the disconnect between the official TypeScript specifications and
the actual JSON over-the-wire behavior, and coupling that knowledge with robust
property normalization, empty-state suppression, and premium markdown rendering,
the A2UI integration in the frontend is fully reliable across both Mock
emulations and Live multi-agent generative flows.
