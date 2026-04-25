---
name: a2ui-rendering
description: >
  Use when an agent renders rich UI back to a client surface (cards,
  dashboards, forms, modals) using the A2UI v0.8.0 declarative protocol.
  Required whenever the response should display structured components
  rather than plain text, or whenever the validate_and_emit_a2ui tool is
  in scope.
license: Apache-2.0
---

# A2UI Rendering

A2UI is a declarative JSON protocol for delivering rich UI from agents
to client surfaces. UI is composed as a flat list of components where
layout containers reference children by ID. The protocol enforces typed
value wrappers and a fixed catalog of 18 primitives.

## When to Compose A2UI

Compose A2UI **only** in response to a user message that needs rich
visual output. Do not generate A2UI on session creation or
proactively. Plain text remains the default for narrative responses.

## Workflow

```
A2UI Render Progress:
- [ ] Decide what information to present
- [ ] Choose primitives (Text, Card, Column/Row, etc.)
- [ ] Compose the surfaceUpdate JSON with unique component IDs
- [ ] Call validate_and_emit_a2ui with the surfaceUpdate JSON
- [ ] If validation fails, fix the violations and re-validate
- [ ] Compose the beginRendering JSON pointing to the root component
- [ ] Call validate_and_emit_a2ui with the beginRendering JSON
- [ ] Wrap both validated payloads in ```a2ui markdown fences
```

`validate_and_emit_a2ui` MUST be called **twice** per surface: once
for `surfaceUpdate` and once for `beginRendering`. Without
`beginRendering`, the frontend will not render the surface.

<!-- [START a2ui_skill_message_structure] -->
## Message Structure

A2UI uses two message types that work together. Both must be emitted.

### surfaceUpdate (defines components)

```json
{
  "surfaceUpdate": {
    "surfaceId": "my-surface",
    "components": [
      {"id": "unique-id", "component": {"TypeName": { ...props }}}
    ]
  }
}
```

- **`surfaceId`**: unique identifier for this UI surface.
- **`components`**: flat array of component definitions (NOT nested trees).
- Each component has **`id`** (unique string) and **`component`**
  (object with exactly one key = the type name).

### beginRendering (tells the frontend which component is root)

```json
{
  "beginRendering": {
    "surfaceId": "my-surface",
    "root": "root-component-id"
  }
}
```

- **`surfaceId`**: must match the surfaceUpdate's surfaceId.
- **`root`**: the `id` of the outermost component (usually a Card).
<!-- [END a2ui_skill_message_structure] -->

<!-- [START a2ui_skill_wrappers] -->
## Typed Value Wrappers

> **CRITICAL**: Never use raw JSON primitives. All values MUST be wrapped.

| Type    | Wrapper                       | Example                               |
|---------|-------------------------------|---------------------------------------|
| String  | `{"literalString": "value"}`  | `"text": {"literalString": "Hello"}`  |
| Number  | `{"literalNumber": 42.0}`     | `"value": {"literalNumber": 3.14}`    |
| Boolean | `{"literalBoolean": true}`    | `"autoplay": {"literalBoolean": true}`|
| Binding | `{"path": "some.data.path"}`  | `"text": {"path": "user.name"}`       |

Raw `"value"`, raw `42`, or raw `true` as property values will be
rejected by `validate_and_emit_a2ui`.
<!-- [END a2ui_skill_wrappers] -->

## Container Children

Layout containers reference children by ID:

- **Multiple children**: `"children": {"explicitList": ["child-id-1", "child-id-2"]}` (NEVER raw arrays)
- **Single child**: `"child": "child-id"` (used by Card, Button)

## Component ID Rules

- IDs **MUST** be unique within a `surfaceUpdate`.
- Use descriptive names: `"title-heading"`, `"main-card"`, `"details-column"`.
- All ID references (`child`, `children.explicitList`,
  `entryPointChild`, `contentChild`, `tabItems[].child`) **MUST**
  resolve to IDs in the same `components` array.

## Component Catalog

For the full catalog of 18 primitives, with required and optional
props plus per-type notes, see [components.md](components.md).

## Examples

For three complete `surfaceUpdate` + `beginRendering` payloads
(simple info card, data list card, dashboard with action button), see
[examples.md](examples.md).
