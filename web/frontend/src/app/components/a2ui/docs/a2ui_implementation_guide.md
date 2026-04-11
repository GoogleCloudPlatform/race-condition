# A2UI Implementation Guide - City Simulator

## Overview

This guide documents the A2UI (Agent-to-User Interface) implementation in the City Simulator frontend. The implementation follows the canonical A2UI specification and adheres to the glassmorphism design system outlined in the project documentation.

## Architecture Components

### 1. A2A Service (`services/a2a.service.ts`)

The A2A Service handles all communication with backend agents using the A2A protocol over Server-Sent Events (SSE).

**Key Features:**
- SSE stream processing with defensive parsing
- Support for both `msg.parts` and `msg.content` payload structures
- Real-time message and surface state management
- Automatic payload extraction and routing

**Usage:**
```typescript
import { A2aService } from './services/a2a.service';

constructor(private a2aService: A2aService) {}

async sendMessage() {
  await this.a2aService.sendMessage('Hello, agent!');
}
```

### 2. A2UI Surface Component (`components/a2ui-surface/a2ui-surface.component.ts`)

The surface component is responsible for rendering A2UI primitives using a recursive template pattern.

**Supported Primitives:**
- **Layout Containers:** Card, Column, Row, List, Modal, Tabs
- **Display Elements:** Text, Image, Icon, Video, Divider
- **Interactive Controls:** Button, TextField

**Key Features:**
- Recursive `ng-template` rendering for nested components
- Glassmorphism styling for all primitives
- Support for both wrapped (`{ Card: { id: '...' }}`) and flat (`{ type: 'Card', id: '...' }`) formats
- Defensive property resolution (`children`, `child`, `items`)

### 3. Hello World Component (Integration Example)

The hello-world component demonstrates full A2UI integration with:
- Real-time chat interface
- Dynamic surface rendering
- Demo A2UI surface generator
- Glassmorphism design system

## Design System

### Glassmorphism Tokens

Following the a2ui_visual_design_system.md specification:

```css
/* Glass Surface */
background: rgba(255, 255, 255, 0.03);
backdrop-filter: blur(20px);
border: 1px solid rgba(255, 255, 255, 0.08);
box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
border-radius: 16px;

/* Typography */
--primary-text: #f1f5f9;
--secondary-text: #94a3b8;
--line-height: 1.6;

/* Interactive Elements */
background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
```

## Message Flow

### 1. User Sends Message

```typescript
sendMessage() {
  await this.a2aService.sendMessage('Plan a marathon route');
}
```

### 2. A2A Service Processes SSE Stream

```typescript
// Service defensively extracts payload
const parts = chunk.parts || chunk.content || [];
```

### 3. A2UI Payload Processing

```typescript
// BeginRendering initializes surface
{
  beginRendering: {
    surfaceId: 'unique-id',
    root: 'root-node-id'
  }
}

// SurfaceUpdate provides components
{
  surfaceUpdate: {
    surfaceId: 'unique-id',
    catalog: 'inline',
    components: [...]
  }
}
```

### 4. Surface Component Renders

```html
<app-a2ui-surface [surface]="surface"></app-a2ui-surface>
```

## Creating A2UI Components

### Example: Dashboard Card

```typescript
const dashboard = {
  beginRendering: {
    surfaceId: 'dashboard-1',
    root: 'main-card'
  }
};

const components = {
  surfaceUpdate: {
    surfaceId: 'dashboard-1',
    catalog: 'inline',
    components: [
      {
        Card: {
          id: 'main-card',
          slots: {
            children: [
              {
                Column: {
                  id: 'col-1',
                  slots: {
                    children: [
                      {
                        Text: {
                          id: 'title',
                          text: 'City Dashboard',
                          usageHint: 'h2'
                        }
                      },
                      {
                        Row: {
                          id: 'stats',
                          slots: {
                            children: [
                              {
                                Text: {
                                  id: 'stat-1',
                                  text: 'Population: 1M'
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
      }
    ]
  }
};
```

## Testing

### Load Demo Surface

The hello-world component includes a `loadDemoSurface()` method that demonstrates:
- BeginRendering initialization
- SurfaceUpdate with complex nested layout
- Multiple primitive types (Card, Column, Row, Text, Divider, Button)
- Data binding and action handling

### Manual Testing

1. Start the dev server: `npm start`
2. Navigate to the hello-world route
3. Click "Load Demo A2UI Surface"
4. Verify glassmorphism styling
5. Test button interactions

## Best Practices

### 1. Defensive Parsing

Always check for both `parts` and `content`:

```typescript
const parts = msg.parts || msg.content || [];
```

### 2. Progressive Rendering

Use stable `messageId` for updates:

```typescript
messageId: this.generateMessageId()
```

### 3. Empty State Handling

Only render surfaces when rootNode exists:

```html
<div *ngIf="rootNode" class="a2ui-surface">
```

### 4. Slot Resolution

Support multiple slot formats:

```typescript
let children = data.children || data.child || data.items;
if (!children && data.slots) {
  children = data.slots.children || data.slots.child || data.slots.items;
}
```

## Troubleshooting

### Issue: Empty Chat Bubbles

**Cause:** Payload extraction not finding `parts` or `content`  
**Solution:** Verify defensive parsing in A2aService

### Issue: Blank A2UI Surface

**Cause:** Missing `beginRendering` or invalid component structure  
**Solution:** Verify payload contains both `beginRendering` and `surfaceUpdate`

### Issue: Styling Not Applied

**Cause:** Incorrect primitive type detection  
**Solution:** Verify `getType()` method returns correct primitive name

## Future Enhancements

- [ ] Add support for Modal and Tabs primitives
- [ ] Implement MultipleChoice and Slider inputs
- [ ] Add markdown rendering for Text primitives
- [ ] Implement progressive tool status pills (⚡/✓)
- [ ] Add data binding support for dynamic updates
- [ ] Integrate with backend agent endpoint

## References

- [A2UI Protocol & Streams](./a2ui_protocol_and_streams.md)
- [A2UI Rendering Strategy](./a2ui_rendering_strategy.md)
- [A2UI Visual Design System](./a2ui_visual_design_system.md)
- [A2UI Implementation Master](./a2ui_implementation_master.md)
- [A2A and A2UI Tutorial](./a2a-and-a2ui-tutorial.md)
