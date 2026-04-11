# A2UI Guide for UI/UX Designers: Designing for Generative Agents

## 1. Introduction: The Paradigm Shift

Traditional UI/UX design follows a **Client-Driven** paradigm. Designers create
rigid layouts (Figma mocks) that engineers build into static code. The server
merely provides raw data, and the client "decides" how to paint it.

**Agent-to-User Interface (A2UI)** flips this. It is a **Server-Driven UI
(SDUI)** protocol where the **Agent is the Designer**.

- **The Agent** constructs a visual layout on-the-fly based on the user's
  specific context.
- **The Client** (Web/Mobile) is a "dumb" renderer that maps a catalog of
  **Primitives** to native styles.

This guide helps you understand how to design the "LEGO blocks" (Primitives) and
"Building Rules" (Composition) that allow agents to create premium, interactive,
and contextual user interfaces.

---

## 2. The A2UI Architecture

To design effectively for A2UI, you must understand its core structural logic.

### 2.1 The Adjacency List Model

Traditional UI data is "nested" (like HTML). This is hard for AI models to
generate reliably. A2UI uses a **Flat Adjacency List**.

- Every element has a unique ID.
- Layout containers (like Columns) simply list the IDs of their children.
- This allows for **Progressive Rendering**: the UI can start appearing on
  screen before the agent has even finished "thinking" about the entire layout.

### 2.2 Generative Plasticity

Because the Agent controls the layout, the UI can adapt to any situation. If a
user asks for a "quick summary," the agent might generate a single `Card`. If
they ask for "detailed analytics," the agent might generate a complex scrollable
`List` of metrics. You aren't designing a fixed page; you are designing a
**capability**.

---

## 3. The Primitives Catalog

A2UI defines 18 universal building blocks. As a designer, your job is to define
the "look and feel" of these blocks so they feel premium no matter how they are
combined.

### 3.1 Structural & Layout Containers

| Primitive   | Design Role                                                                                        |
| :---------- | :------------------------------------------------------------------------------------------------- |
| **Column**  | Stacks elements vertically. Supports `distribution` (start, center, spaceBetween) and `alignment`. |
| **Row**     | Arranges elements horizontally. Core for headers and metadata bars.                                |
| **Card**    | An elevated, glassmorphic container. The default "frame" for grouped information.                  |
| **List**    | A scrollable container (vertical or horizontal) for repeating items.                               |
| **Tabs**    | Organizes content into switchable views.                                                           |
| **Modal**   | A blocking overlay for high-focus tasks (e.g., confirmations, complex forms).                      |
| **Divider** | A subtle visual line (horizontal or vertical) to separate sections.                                |

### 3.2 Display Elements

| Primitive       | Design Role                                                                         |
| :-------------- | :---------------------------------------------------------------------------------- |
| **Text**        | Supports semantic hints (`h1` through `h5`, `body`, `caption`).                     |
| **Icon**        | Access to a standard set of symbolic glyphs (e.g., `check`, `warning`, `settings`). |
| **Image**       | For remote assets. Supports `fit` rules (`cover`, `contain`) and usage hints.       |
| **Video/Audio** | Native media players for rich content delivery.                                     |

### 3.3 Interactive & Input Elements

| Primitive          | Design Role                                                                  |
| :----------------- | :--------------------------------------------------------------------------- |
| **Button**         | The primary action trigger. Can be `primary` (vibrant) or neutral.           |
| **TextField**      | For user input. Supports `date`, `number`, `obscured`, and multi-line modes. |
| **MultipleChoice** | Dropdowns or radio lists for selecting from a set of options.                |
| **CheckBox**       | Boolean toggle for settings or confirmations.                                |
| **Slider**         | Numeric range selector.                                                      |

---

## 4. Composition: The LEGO Philosophy

Designing for A2UI is like designing a LEGO set. You provide the blocks and the
instructions (prompts), and the Agent builds the structure.

### 4.1 Layout Nesting

Agent-generated UIs often follow a recursive pattern: `Card` -> `Column` ->
`Row` -> (`Icon` + `Text`).

### 4.2 Progressive Integrity

Always account for the "streaming" state. In A2UI, parts of the UI can arrive
sequentially. Your design system must handle loading states gracefully—often
using skeleton screens or stable visual anchors.

---

## 5. Visual Language: Glassmorphism & Premium Aesthetics

![A2UI Design System Mockup](file:///Users/caseywest/.gemini/antigravity/brain/6b5391b1-d34b-4f93-bc3e-4c7f3fc3efc3/a2ui_design_system_mockup_1772439630751.png)

The default A2UI design system for this project uses **Glassmorphism**. This
creates a high-end, "spatial" feel that blends the agent's generative output
with the host application.

### 5.1 The Glass Surface

- **Background**: `rgba(255, 255, 255, 0.03)`
- **Blur**: `20px backdrop-filter`
- **Border**: `1px solid rgba(255, 255, 255, 0.08)`
- **Shadow**: Deep, soft shadows to create depth.

### 5.2 Interaction Pills (⚡/✓)

A2UI uses **Pills** to make hidden agent orchestration visible.

- **⚡ Call Pill**: "Agent is calling a specialist..." (Indicates background
  work).
- **✓ Response Pill**: "Data received." (Replaces the call pill once the task is
  done).

---

## 6. Examples & Possibilities

### Example A: The Interactive Route Dashboard

When a Marathon Planner agent proposes a route, it doesn't just send text. It
composes a dashboard using the following logic:

```json
{
  "type": "Card",
  "child": {
    "type": "Column",
    "children": [
      { "type": "Text", "text": "Proposed Marathon Route", "usageHint": "h2" },
      { "type": "Divider" },
      {
        "type": "Row",
        "distribution": "spaceBetween",
        "children": [
          { "type": "Text", "text": "Traffic Logistics", "usageHint": "h5" },
          {
            "type": "Row",
            "children": [
              { "type": "Icon", "name": "check" },
              { "type": "Text", "text": "Verified" }
            ]
          }
        ]
      },
      {
        "type": "Button",
        "primary": true,
        "child": { "type": "Text", "text": "Approve Route" },
        "action": { "name": "approve_route" }
      }
    ]
  }
}
```

### Example B: The Data-Binding Form

A user wants to sign up for a volunteer shift. The agent generates a `Modal`
containing a `TextField` for their name and a `MultipleChoice` for their shift
preference.

```json
{
  "type": "Modal",
  "entryPointChild": {
    "type": "Button",
    "child": { "type": "Text", "text": "Volunteer Sign Up" }
  },
  "contentChild": {
    "type": "Card",
    "child": {
      "type": "Column",
      "children": [
        { "type": "Text", "text": "Registration", "usageHint": "h3" },
        { "type": "TextField", "label": { "literalString": "Full Name" } },
        {
          "type": "MultipleChoice",
          "options": [
            { "label": { "literalString": "Morning" }, "value": "am" },
            { "label": { "literalString": "Afternoon" }, "value": "pm" }
          ],
          "selections": { "path": "/volunteer/shift" }
        },
        {
          "type": "Button",
          "primary": true,
          "child": { "type": "Text", "text": "Submit" },
          "action": { "name": "submit_registration" }
        }
      ]
    }
  }
}
```

---

## 7. Best Practices for A2UI Designers

1. **Design Primitives, Not Pages**: Focus on the universal behavior of a `Card`
   or a `Button`.
2. **Context is King**: Expect the agent to add or remove elements based on the
   user's dialogue. The layout should be "elastic."
3. **Data Binding Awareness**: Remember that every element can be "bound" to
   live data. A price field in a `Text` node can update in real-time as the
   agent calculates it.
4. **No Magic Widgets**: Avoid custom components for specific tasks (like a
   "Weather Widget"). Encourage the agent to compose it using standard `Rows`,
   `Columns`, and `Icons`.
