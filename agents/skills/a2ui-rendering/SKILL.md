---
name: a2ui-rendering
description: >
  Teaches the agent to compose A2UI v0.8.0 rich UI payloads generatively.
  Provides the validate_and_emit_a2ui tool for compliance validation.
metadata:
  adk_additional_tools:
    - validate_and_emit_a2ui
---

# A2UI Rendering

## A2UI Overview

A2UI is a declarative JSON protocol for delivering rich UI from agents to
client surfaces. You compose UI as flat component lists where layout
containers reference children by ID. The protocol enforces typed value
wrappers and a fixed catalog of 18 primitives.

## Output Format

When you need to present rich UI to the user:

1. Compose your A2UI JSON payload following the structure below.
2. **ALWAYS** call `validate_and_emit_a2ui` with your JSON string before
   presenting it. The tool returns:
   - `{"status": "success", "a2ui": ...}` on valid payloads.
   - `{"status": "error", "violations": [...]}` with specific fixes needed.
3. Wrap validated A2UI JSON in ` ```a2ui ` markdown fences in your response.

<!-- [START a2ui_skill_message_structure] -->
## Message Structure

A2UI uses two message types that work together. You MUST emit both for
the frontend to render your UI.

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
- Each component has **`id`** (unique string) and **`component`** (object
  with exactly one key = the type name).

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
- **Without beginRendering, the frontend will NOT render your surface.**
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

**NEVER** use raw `"value"`, raw `42`, or raw `true` as property values.
<!-- [END a2ui_skill_wrappers] -->

## Container Children

Layout containers reference children by ID:

- **Multiple children**: `"children": {"explicitList": ["child-id-1", "child-id-2"]}` (NEVER raw arrays)
- **Single child**: `"child": "child-id"` (used by Card, Button)

## The 18 Standard Catalog Primitives

### Layout

| Type    | Required Props                      | Optional Props             | Notes                                  |
|---------|-------------------------------------|----------------------------|----------------------------------------|
| Column  | `children`                          | `distribution`, `alignment`| Vertical container                     |
| Row     | `children`                          | `distribution`, `alignment`| Horizontal container                   |
| List    | `children`                          | `direction`, `alignment`   | Scrollable container                   |
| Card    | `child`                             | --                         | Single-child wrapper with elevated styling |
| Tabs    | `tabItems`                          | --                         | Each item: `{"title": wrapped_string, "child": "id"}` |
| Modal   | `entryPointChild`, `contentChild`   | --                         | Overlay dialog                         |
| Divider | --                                  | `axis`                     | Default horizontal                     |

### Display

| Type        | Required Props    | Optional Props               | Notes                                       |
|-------------|-------------------|------------------------------|---------------------------------------------|
| Text        | `text` (wrapped)  | `usageHint`                  | Hints: h1-h5, body, caption, title, label   |
| Image       | `url` (wrapped)   | `fit`, `usageHint`           |                                             |
| Icon        | `name` (wrapped)  | --                           | Material icon names                         |
| Video       | `url` (wrapped)   | `autoplay` (wrapped bool)    |                                             |
| AudioPlayer | `url` (wrapped)   | `description` (wrapped)      |                                             |

### Input

| Type           | Required Props       | Optional Props                    | Notes                                  |
|----------------|----------------------|-----------------------------------|----------------------------------------|
| Button         | `child`, `action`    | `primary`                         | `child` = component ID, `action` = `{"name": "action_name"}` |
| TextField      | `label` (wrapped)    | `text`, `textFieldType`           |                                        |
| CheckBox       | `label` (wrapped)    | `value`                           |                                        |
| Slider         | `value`              | `minValue`, `maxValue`            |                                        |
| MultipleChoice | `selections`         | `options`, `maxAllowedSelections` |                                        |
| DateTimeInput  | --                   | `value`, `enableDate`, `enableTime`|                                       |

## Component ID Rules

- IDs **MUST** be unique within a `surfaceUpdate`.
- Use descriptive names: `"title-heading"`, `"main-card"`, `"details-column"`.
- All ID references (`child`, `children.explicitList`, `entryPointChild`,
  `contentChild`, `tabItems[].child`) **MUST** resolve to IDs in the same
  `components` array.

## Examples

### Example 1: Simple Info Card

**Call 1 — surfaceUpdate:**
```json
{
  "surfaceUpdate": {
    "surfaceId": "info",
    "components": [
      {"id": "heading", "component": {"Text": {"text": {"literalString": "Status Report"}, "usageHint": "h2"}}},
      {"id": "body", "component": {"Text": {"text": {"literalString": "All systems operational."}, "usageHint": "body"}}},
      {"id": "content-col", "component": {"Column": {"children": {"explicitList": ["heading", "body"]}}}},
      {"id": "main-card", "component": {"Card": {"child": "content-col"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**
```json
{"beginRendering": {"surfaceId": "info", "root": "main-card"}}
```

### Example 2: Data List Card

**Call 1 — surfaceUpdate:**
```json
{
  "surfaceUpdate": {
    "surfaceId": "sponsors",
    "components": [
      {"id": "title", "component": {"Text": {"text": {"literalString": "Event Sponsors"}, "usageHint": "h3"}}},
      {"id": "divider", "component": {"Divider": {}}},
      {"id": "s1", "component": {"Text": {"text": {"literalString": "Acme Corp"}}}},
      {"id": "s2", "component": {"Text": {"text": {"literalString": "Globex Inc"}}}},
      {"id": "s3", "component": {"Text": {"text": {"literalString": "Initech"}}}},
      {"id": "sponsor-list", "component": {"List": {"children": {"explicitList": ["s1", "s2", "s3"]}}}},
      {"id": "content", "component": {"Column": {"children": {"explicitList": ["title", "divider", "sponsor-list"]}}}},
      {"id": "card", "component": {"Card": {"child": "content"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**
```json
{"beginRendering": {"surfaceId": "sponsors", "root": "card"}}
```

### Example 3: Dashboard with Metrics and Action Button

**Call 1 — surfaceUpdate:**
```json
{
  "surfaceUpdate": {
    "surfaceId": "dashboard",
    "components": [
      {"id": "dash-title", "component": {"Text": {"text": {"literalString": "Marathon Dashboard"}, "usageHint": "h2"}}},
      {"id": "sep1", "component": {"Divider": {}}},
      {"id": "metric1", "component": {"Text": {"text": {"literalString": "Safety Score: 0.92 (Pass)"}}}},
      {"id": "metric2", "component": {"Text": {"text": {"literalString": "Logistics: 0.85 (Pass)"}}}},
      {"id": "metric3", "component": {"Text": {"text": {"literalString": "Budget: 0.78 (Warning)"}}}},
      {"id": "metrics-col", "component": {"Column": {"children": {"explicitList": ["metric1", "metric2", "metric3"]}}}},
      {"id": "sep2", "component": {"Divider": {}}},
      {"id": "btn-label", "component": {"Text": {"text": {"literalString": "Run Simulation"}}}},
      {"id": "run-btn", "component": {"Button": {"child": "btn-label", "action": {"name": "run_simulation"}, "primary": {"literalBoolean": true}}}},
      {"id": "content-col", "component": {"Column": {"children": {"explicitList": ["dash-title", "sep1", "metrics-col", "sep2", "run-btn"]}}}},
      {"id": "dashboard-card", "component": {"Card": {"child": "content-col"}}}
    ]
  }
}
```

**Call 2 — beginRendering:**
```json
{"beginRendering": {"surfaceId": "dashboard", "root": "dashboard-card"}}
```

## Workflow

**Only compose A2UI when you have information to present in response to a user
message.** Do NOT proactively generate A2UI on session creation or without a
user request.

When you do need to present rich UI:

1. Decide what information to present based on the user's request.
2. Choose appropriate primitives (Text for data, Card for containers,
   Column/Row for layout).
3. Compose the `surfaceUpdate` JSON with unique component IDs.
4. Call `validate_and_emit_a2ui` with the surfaceUpdate JSON string.
5. If validation fails, fix the violations and re-validate.
6. Compose the `beginRendering` JSON pointing to the root component ID.
7. Call `validate_and_emit_a2ui` with the beginRendering JSON string.
8. Include the validated payloads in your response wrapped in
   ` ```a2ui ` fences.

**You MUST call `validate_and_emit_a2ui` TWICE** — once for
`surfaceUpdate` and once for `beginRendering`. Without `beginRendering`,
the frontend will not render your surface.
