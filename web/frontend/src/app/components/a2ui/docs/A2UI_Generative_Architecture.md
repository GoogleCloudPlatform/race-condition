# Generative User Interfaces via the A2UI Specification

## Server-Driven Primitive Composition in Multi-Agent Systems

By Casey West

---

## 1. Introduction: The A2UI Paradigm Shift

The Agent-to-User Interface (A2UI) protocol, developed by Google, represents a
foundational shift in how human-computer interaction is modeled in the age of
generative artificial intelligence. For decades, UI engineering has been
dictated by the "Client-Driven" paradigm: human engineers write rigid HTML, CSS,
and JavaScript components that are permanently compiled into the application
bundle. In this model, the server merely provides static JSON data (e.g.,
`{"score": 95}`); the client natively knows _how_ to draw a scoreboard based on
that data.

A2UI introduces a **Server-Driven UI (SDUI)** architecture mapped seamlessly to
Large Language Models (LLMs). Rather than the client application dictating the
layout, the remote AI agent assumes absolute control over the visual
presentation layer. It constructs a declarative JSON graph representing the
exact UI structure required for the moment and streams this graph to a "dumb"
client renderer. The client's only responsibility is to interpret the JSON nodes
into native display elements safely, bridging the gap between an LLM's vast
computational reasoning and the user's screen.

This document explores the two dominant implementation vectors within the A2UI
framework: **Custom Components** and **Generative Primitive Composition**.

---

## 2. The Mechanics of the A2UI Architecture

At its core, A2UI revolves around the concept of a `Surface`. A Surface is an
isolated, visually contained rectangle on a user's screen (such as a modal
window, a sidebar, or an inline chat bubble).

When an agent needs to communicate an interface to the user, it packages a
`SurfaceUpdateMessage` encoded over the JSON-RPC Agent-to-Agent (A2A) protocol.
This message contains an array of UI component definitions built strictly from a
designated library called a **Catalog**.

### The Message Processor

The true power of an A2UI client lies in the `MessageProcessor`. Raw JSON
payloads from the agent are mathematically unsafe—they may contain unbound data
references or malicious code. When the client receives a payload, the
`MessageProcessor`:

1. **Hydrates the Component Tree:** Resolves the parent-child adjacency list
   model described by the agent into a concrete object graph.
2. **Binds the Data Model:** Maps discrete data references (e.g.,
   `/user/profile/name`) strictly to localized application state paths to
   prevent cross-surface memory scraping.
3. **Mounts the Native Element:** Hands the validated, typed object graph back
   to the local framework (React, Angular, iOS Swift) for native visual
   rendering.

---

## 3. The Custom Component Model (Path B)

The A2UI specification allows developers to create bespoke, highly specialized
UI elements through the **Custom Catalog** mechanism.

### How it Works

1. **Compilation Phase:** A UI engineer writes a custom framework component
   (e.g., an Angular `<simulation-result>`).
2. **Registration Phase:** The developer registers this component within the
   A2UI client initialization step, linking the string
   `"a2ui-simulation-result"` to the executing code.
3. **Generative Phase:** The remote LLM outputs JSON containing
   `"type": "a2ui-simulation-result", "props": {"score": 95}`. The
   `MessageProcessor` identifies the key, looks up the custom component in the
   catalog, and renders it.

### Limitations of Custom Components

While powerful for injecting tightly controlled legacy code (such as a
proprietary D3.js charting engine or a complex interactive map), Custom
Components **defeat the generative capabilities of the LLM.**

When an LLM is forced to use `"type": "a2ui-simulation-result"`, it is trapped
in a rigid box. It can populate the `score` field, but it **cannot** decide to
add a new "Historical Averages" column to the readout, nor can it dynamically
inject an "Approve Budget" warning button if the simulation identifies a
critical cost overrun.

The layout is static, pre-compiled, and immune to the contextual reasoning the
LLM was hired to perform.

---

## 4. The Power of Generative Primitive Composition (Path A)

The true breakthrough of A2UI lies in its **Default Catalog**—a comprehensive
library of simple, atomic UI building blocks. When an LLM generates a layout
using these blocks, it calculates the interface dynamically, responding to the
specific nuances of a user's prompt in ways that pre-compiled components simply
cannot.

### The Complete Default Catalog Reference Manual

The A2UI `DEFAULT_CATALOG` (`a2ui.org:standard_catalog_0_8_0`) defines a strict
ontology of 18 universal primitives. The following is an exhaustive
architectural schema detailing every component and its exact payload attributes.
All properties accept either literal types (e.g., `literalString`,
`literalBoolean`) or data model bindings (`path`).

#### Structural & Layout Containers

**1. `Column`** Vertically stacks child components.

- **`children`** [Required]: Object specifying the children. Accepts either
  `explicitList` (array of child IDs) or `template` (object containing
  `componentId` and `dataBinding` to iterate over model arrays).
- **`distribution`**: String enum (`start`, `center`, `end`, `spaceBetween`,
  `spaceAround`, `spaceEvenly`) defining vertical `justify-content`.
- **`alignment`**: String enum (`center`, `end`, `start`, `stretch`) defining
  horizontal `align-items`.

**2. `Row`** Horizontally distributes child components.

- **`children`** [Required]: Child definition array or list template.
- **`distribution`**: String enum (`start`, `center`, `end`, `spaceBetween`,
  `spaceAround`, `spaceEvenly`) defining horizontal `justify-content`.
- **`alignment`**: String enum (`start`, `center`, `end`, `stretch`) defining
  vertical `align-items`.

**3. `List`** A scrollable data-driven or static array container.

- **`children`** [Required]: Child definition array or list template.
- **`direction`**: String enum (`vertical`, `horizontal`) dictating scroll axis.
- **`alignment`**: String enum (`start`, `center`, `end`, `stretch`).

**4. `Card`** An elevated, visually distinct framing component.

- **`child`** [Required]: A single component ID (String) to render inside the
  card padding.

**5. `Tabs`** Organizes disparate UI trees under selectable navigation headers.

- **`tabItems`** [Required]: Array of objects containing:
  - **`title`** [Required]: String or datapath for the tab label.
  - **`child`** [Required]: Component ID string mapping to the tab's interior
    content.

**6. `Modal`** A blocking dialog overlay.

- **`entryPointChild`** [Required]: Component ID (usually a Button) that
  triggers the modal open event.
- **`contentChild`** [Required]: Component ID representing the content inside
  the dialog.

**7. `Divider`** A visual axis separator.

- **`axis`**: String enum (`horizontal`, `vertical`) dictating orientation.

#### Display Elements

**8. `Text`** Renders typography.

- **`text`** [Required]: Literal string or datapath string.
- **`usageHint`**: String enum mapping to text scale/weight: `h1`, `h2`, `h3`,
  `h4`, `h5`, `caption`, `body`.

**9. `Image`** Displays remote image assets.

- **`url`** [Required]: Literal string or datapath targeting the remote image
  URL.
- **`fit`**: String enum (`contain`, `cover`, `fill`, `none`, `scale-down`)
  mimicking CSS `object-fit`.
- **`usageHint`**: String enum defining strict bounding box rules: `icon`,
  `avatar`, `smallFeature`, `mediumFeature`, `largeFeature`, `header`.

**10. `Icon`** Renders standardize material UI symbolic glyphs.

- **`name`** [Required]: Literal string matching exactly 49 pre-defined enums
  (e.g., `accountCircle`, `check`, `warning`, `shoppingCart`, `download`,
  `share`, `settings`).

**11. `Video`** Embeds a remote video stream.

- **`url`** [Required]: Literal string or datapath targeting the video source.

**12. `AudioPlayer`** Manages audio playback UI natively.

- **`url`** [Required]: Literal string or datapath targeting the audio source.
- **`description`**: Optional string/datapath for audio title metadata.

#### Interactive & Input Controls

**13. `Button`** Triggers a localized `UserAction` payload back to the remote
server via JSON-RPC.

- **`child`** [Required]: Component ID representing the button interior (usually
  a `Text` or `Icon` node).
- **`action`** [Required]: Object defining the output dispatch:
  - **`name`** [Required]: String representing the action keyword.
  - **`context`**: Array of objects (`key` and `value`) mapping explicit literal
    types or datapaths to append to the action payload.
- **`primary`**: Boolean dictating primary call-to-action styling.

**14. `TextField`** Captures string inputs natively.

- **`label`** [Required]: Literal string/datapath dictating the input hint.
- **`text`**: Literal string/datapath seeding initial content.
- **`textFieldType`**: String enum (`date`, `longText`, `number`, `shortText`,
  `obscured`) dictating the HTML DOM element type.
- **`validationRegexp`**: Client-side validation regex string.

**15. `MultipleChoice`** A standard radio/dropdown array heavily bound to
application state.

- **`selections`** [Required]: Bound data array (`path`) or literal array
  reflecting selected values.
- **`options`** [Required]: Array of available explicit choices containing:
  - **`label`** [Required]: Literal string/datapath for the option text.
  - **`value`** [Required]: String value returned to the `selections` variable.
- **`maxAllowedSelections`**: Integer enforcing single-select (1) vs
  multi-select behaviors.

**16. `CheckBox`** A boolean toggle bound to application state.

- **`label`** [Required]: Literal string/datapath for label text.
- **`value`** [Required]: Bound data path or `literalBoolean` representing
  current state (true/false).

**17. `Slider`** A numeric slider mechanism.

- **`value`** [Required]: Bound datapath or `literalNumber` for the active mark.
- **`minValue`**: Number dictating the ground floor.
- **`maxValue`**: Number dictating the ceiling.

**18. `DateTimeInput`** A high-level OS-native date/time picker.

- **`value`** [Required]: Bound datapath or `literalString` for the current ISO
  stamp.
- **`enableDate`**: Boolean.
- **`enableTime`**: Boolean.
- **`outputFormat`**: String formatting rule (e.g. `YYYY-MM-DD`).

---

### Advanced Composition: Building Rich Interfaces

By combining these atomic LEGO bricks, an LLM can construct infinitely complex
and deeply interactive interfaces on the fly. Consider the following
architectural examples that entirely circumvent the need for a human UI
engineer:

#### Example 1: The Interactive Route Approval Dashboard

Imagine a user asks a marathon planning agent to devise a route that touches
historical landmarks. The LLM calculates the route, but identifies a cost
overrun. It decides, at runtime, to generate a hybrid "Approval Dashboard"
highlighting the issue:

```json
{
  "type": "Card",
  "children": [
    {
      "type": "Column",
      "children": [
        {
          "type": "Text",
          "text": "Proposed Marathon Route: The Patriot Trail",
          "usageHint": "h2"
        },
        { "type": "Divider" },
        {
          "type": "Row",
          "distribution": "spaceBetween",
          "children": [
            {
              "type": "Column",
              "children": [
                {
                  "type": "Text",
                  "text": "Traffic Logistics",
                  "usageHint": "h5"
                },
                {
                  "type": "Row",
                  "children": [
                    { "type": "Icon", "name": "check" },
                    {
                      "type": "Text",
                      "text": "Passed: Route verified by DOT API."
                    }
                  ]
                }
              ]
            },
            {
              "type": "Column",
              "children": [
                {
                  "type": "Text",
                  "text": "Cost Projections",
                  "usageHint": "h5"
                },
                {
                  "type": "Row",
                  "children": [
                    { "type": "Icon", "name": "warning" },
                    {
                      "type": "Text",
                      "text": "Failed: Exceeds budget by $45,000."
                    }
                  ]
                }
              ]
            }
          ]
        },
        { "type": "Divider" },
        {
          "type": "Row",
          "children": [
            {
              "type": "Button",
              "action": { "name": "Recalculate_Budget" },
              "child": { "type": "Text", "text": "Optimize Finances" }
            },
            {
              "type": "Button",
              "primary": true,
              "action": {
                "name": "Force_Approve",
                "context": [
                  {
                    "key": "override_cost",
                    "value": { "literalBoolean": true }
                  }
                ]
              },
              "child": { "type": "Text", "text": "Approve Anyway" }
            }
          ]
        }
      ]
    }
  ]
}
```

**Why this is revolutionary:** No Angular or React code was ever written for a
"Traffic vs. Cost Approval Panel." The LLM combined `Columns`, `Rows`, `Icons`
mapped to `check` and `warning`, and dynamic `Buttons` loaded with specific JSON
context payloads to route actions back to backend sub-agents.

#### Example 2: The On-the-Fly User Registration Form

A user requests to sign up as a volunteer for the marathon. Instead of
redirecting them to a web portal, the LLM intercepts the intent and constructs a
data-entry modal entirely out of basic I/O primitives:

```json
{
  "type": "Modal",
  "entryPointChild": {
    "type": "Button",
    "primary": true,
    "child": { "type": "Text", "text": "Sign Up to Volunteer" },
    "action": { "name": "open_signup" }
  },
  "contentChild": {
    "type": "Card",
    "child": {
      "type": "Column",
      "children": [
        { "type": "Text", "text": "Volunteer Registration", "usageHint": "h3" },
        {
          "type": "TextField",
          "label": { "literalString": "Full Name" },
          "textFieldType": "shortText"
        },
        { "type": "DateTimeInput", "enableDate": true, "enableTime": false },
        {
          "type": "MultipleChoice",
          "maxAllowedSelections": 1,
          "options": [
            { "label": { "literalString": "Water Station" }, "value": "water" },
            { "label": { "literalString": "Medical Tent" }, "value": "medical" }
          ],
          "selections": { "path": "/volunteer/assignment" }
        },
        { "type": "Divider" },
        {
          "type": "Button",
          "primary": true,
          "action": { "name": "Submit_Volunteer_Form" },
          "child": { "type": "Text", "text": "Confirm Assignment" }
        }
      ]
    }
  }
}
```

**Why this is revolutionary:** The LLM bound the `MultipleChoice` dropdown
directly to an A2UI client-managed state path (`/volunteer/assignment`). When
the user clicks "Confirm Assignment", the client perfectly packages the values
entered into the `TextField` and `MultipleChoice` drop-down, transmitting an
atomic JSON-RPC update back to the server without any custom React hooking
logic.

---

### Strategic Benefits of Primitive Composition

1. **Contextual Plasticity:** The UI is dynamically assembled specific to the
   immediate conversational context. If the user asks, "Plan the marathon, but
   only show me the budget," the LLM simply omits the `Row` primitives related
   to Traffic Logistics and constructs a new layout prioritizing financial
   numbers. The interface adapts exactly to the user's mental model.
2. **Zero-Deploy Interation:** Because the LLM determines the layout structure,
   adding new features (like an embedded `TextField` for user feedback) requires
   exactly zero changes to the compiled client binary. Engineering focus shifts
   entirely from writing CSS and HTML templates to writing robust Python prompts
   and capability handlers on the server.
3. **Emergent Interfaces:** LLMs can synthesize visual metaphors that human
   engineers did not explicitly program. Given a standard set of geometric and
   typographic constraints, the agent can invent novel ways of displaying data
   relationships, creating truly "purpose-built" user interfaces unique to every
   session.

---

## 6. Visualizing the Hidden Orchestration

In Path A (Generative), the model has full control over the UI. However, in
complex multi-agent systems, much of the intelligence happens in sub-agent
orchestration (A2A delegation).

A2UI provides a standard mechanism for orchesration visibility: **Interaction
Pills**.

### Patterns for Server-Driven Visibility

- **Tool Call Propagation**: When an orchestrator agent invokes a specialist, it
  should emit a `DataPart` event (⚡) via real-time SSE before the specialist
  even starts processing.
- **Result Commitment**: Once the specialist returns, the orchestrator updates
  the same visual anchor with a completion signal (✓).

By manifesting these hidden "thoughts" and "delegations" via A2UI primitives (or
specialized `DataPart` indicators), we satisfy the user's need for transparency
in complex reasoning chains without sacrificing the speed and flexibility of
generative UI.
