# A2UI Rendering Strategy & Generative UI Ethos

## The Recursive Rendering Pattern

A2UI surfaces are tree structures. To render them with high fidelity in Angular,
use a recursive `ng-template` approach. This ensures that a `Card` can contain a
`Column`, which can contain another `Row`, indefinitely.

### Implementation Pattern

```html
<ng-template #renderer let-node="node" let-surface="surface">
  <div [class]="getType(node)">
    <!-- Layout Handling -->
    <ng-container *ngIf="isLayout(node)">
      <ng-container *ngFor="let child of getChildren(node)">
        <ng-container
          *ngTemplateOutlet="renderer; context: { node: child, surface: surface }"
        ></ng-container>
      </ng-container>
    </ng-container>

    <!-- Primitive Handling -->
    <span *ngIf="getType(node) === 'Text'"
      >{{ getContent(node, surface) }}</span
    >
    <img *ngIf="getType(node) === 'Image'" [src]="node.Image.src" />
  </div>
</ng-template>
```

## Generative UI Ethos

The core philosophy of A2UI is that the **Agent drives the UI**, not the
frontend developer.

### Rules for Canonical Adherence

1. **Strict Catalog Usage**: Stick to primitives defined in the Canonical A2UI
   catalog (`Card`, `Column`, `Row`, `Text`, `Button`, etc.).
2. **No Specialized Widgets**: Avoid building custom "Weather Widgets" or "SVG
   Charts" in the frontend. If the model needs to show a weather report, it
   should compose it using `Card`, `Row`, and `Text`.
3. **Model Compatibility**: When the UI uses standard primitives, the LLM can
   reason about the layout. If the UI relies on custom "magic" components, the
   LLM may fail to use them correctly.

## Data Binding

Use the `bind` property on A2UI primitives to map component fields to the
`Types.Surface.data` object. This allows for efficient "generative updates"
where the backend sends new values without re-sending the entire UI tree.

### Example

- **Node**: `{ "Text": { "id": "price", "bind": "currentPrice" } }`
- **Surface Data**: `{ "currentPrice": "$14.99" }`
- **Result**: Renders "$14.99" and updates instantly when `currentPrice`
  changes.
