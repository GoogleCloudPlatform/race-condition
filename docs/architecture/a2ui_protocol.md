# A2UI Protocol Reference (v0.8.0)

A2UI (Agent-to-User Interface) is a schema-driven protocol that lets agents
send UI components to frontends as structured message parts. Race Condition
follows the `a2ui.org:standard_catalog_0_8_0` specification.

## Core rules

- **Capitalized primitives.** All component types use capitalized names
  (`Video`, `Card`, `Column`).
- **Direct properties.** Component properties are mapped onto the component
  object, not nested under a `props` key.
- **Recursive composition.** Containers (`Column`, `Row`, `Card`) host other
  components via `children` (array) or `child` (single).
- **Composed, not bespoke.** Layouts are built from the catalog primitives.
  Don't add custom one-off types.

## Message Structure

An A2UI payload is strictly a JSON object wrapped in an `a2ui` markdown block:

```json
{
  "type": "Card",
  "child": {
    "type": "Column",
    "children": [
      {
        "type": "Text",
        "text": "Alert: Simulation Spike",
        "usageHint": "h2"
      },
      {
        "type": "Button",
        "primary": true,
        "child": "Acknowledge"
      }
    ]
  }
}
```

## The Default Catalog (18 Primitives)

| Type | Category | Description |
| :--- | :--- | :--- |
| **Column** | Layout | Vertical container (`distribution`, `alignment`). |
| **Row** | Layout | Horizontal container (`distribution`, `alignment`). |
| **List** | Layout | Scrollable array of children. |
| **Card** | Layout | Elevated surface container. |
| **Tabs** | Layout | Tabbed navigation (`tabItems`). |
| **Modal** | Layout | Blocking interaction overlay. |
| **Divider** | Layout | Structural separator (`axis`). |
| **Text** | Display | Rich typography (`usageHint`: `h1`-`h5`, `body`, `caption`). |
| **Image** | Display | Remote asset display (`fit`, `usageHint`). |
| **Icon** | Display | Material symbolic glyphs. |
| **Video** | Display | Media playback (`url`, `autoplay`). |
| **AudioPlayer** | Display | Audio playback (`url`, `description`). |
| **Button** | Input | Interactive dispatch (`child`, `primary`). |
| **TextField** | Input | String input (`label`, `textFieldType`). |
| **MultipleChoice** | Input | Selection array (`options`, `selections`). |
| **CheckBox** | Input | Boolean toggle (`label`, `value`). |
| **Slider** | Input | Numeric range input (`minValue`, `maxValue`). |
| **DateTimeInput** | Input | Temporal selection (`enableDate`, `enableTime`). |

## Implementation

### Backend (Python)

Agents compose A2UI payloads inline through the shared `a2ui-rendering` skill
at `agents/skills/a2ui-rendering/`. The skill bundles the v0.8.0 specification
into the agent's context and exposes a single tool, `validate_and_emit_a2ui`,
that validates the JSON before it leaves the process.

Agents opt in just by being constructed with `load_agent_skills()` — the
shared skills directory is auto-discovered. From the agent's perspective:

```python
# Inside a tool or as part of a model response, the agent calls:
result = await validate_and_emit_a2ui(
    payload=json.dumps({
        "surfaceUpdate": {
            "id": "alert-1",
            "components": [
                {"id": "alert-card", "type": "Card", "child": "alert-text"},
                {"id": "alert-text", "type": "Text", "text": "System Alert",
                 "usageHint": "h3"},
            ],
        },
    }),
    tool_context=ctx,
)
# result is {"status": "success", "a2ui": <validated_payload>} on success,
# or {"status": "error", "violations": [...], "suggestion": "..."} on failure.
```

There is no separate "library" call site. The tool is the contract; if the JSON
isn't valid A2UI, validation fails and the model gets actionable feedback.

### Frontend (vanilla TS)

The `tester` UI uses a recursive renderer in `web/tester/src/a2ui/index.ts`.
All 18 primitives are mapped in the `REGISTRY`.
