# A2UI Protocol Reference (v0.8.0 Standard)

A2UI (Agent-to-User Interface) is a schema-driven protocol that lets AI agents send UI components to frontends via standard message parts.

The Race Condition project strictly follows the **a2ui.org:standard_catalog_0_8_0** specification.

## Core Philosophy

- **Capitalized Primitives**: All component types MUST use capitalized names (e.g., `Video`, `Card`, `Column`).
- **Direct Properties**: Properties are mapped directly to the component object.
- **Recursive Composition**: Containers like `Column`, `Row`, and `Card` can host other components via `children` (array) or `child` (single) properties.
- **LLM-Driven Layout**: Layout uses composition of atomic primitives instead of custom one-off components.

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
| **Card** | Layout | Elevated container with glassmorphism styling. |
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

### Backend (Python) — Generative Approach (Recommended)

Agents can compose A2UI directly by including the shared `a2ui-rendering` skill
from `agents/skills/a2ui-rendering/`. The skill teaches the LLM the full A2UI
v0.8.0 specification and provides a `validate_and_emit_a2ui` tool for compliance
validation.

Agents opt in by having `load_agent_skills()` discover the shared skill
automatically. The LLM then composes A2UI payloads inline, validates them, and
includes them in its response.

### Backend (Python) — Programmatic Approach

For complex data-driven layouts or testing scenarios, use the
`agents.utils.a2ui` library directly:

```python
from agents.utils import a2ui

def show_alert():
    return a2ui.create_payload("Card", {
        "child": {"type": "Text", "text": "System Alert", "usageHint": "h3"}
    })
```

### Frontend (Vanilla TS)

The `tester` UI uses a recursive renderer in `web/tester/src/a2ui/index.ts`. All 18 primitives are mapped in the `REGISTRY`.

