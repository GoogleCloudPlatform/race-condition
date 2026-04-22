# A2UI Architecture Diagrams

## Data Flow: Agent to UI

This diagram illustrates how a generative response moves from the multi-agent
backend to the visual pixels on the screen.

```mermaid
graph TD
    subgraph "Backend (Python ADK / Swarm)"
        A[Generative Agent] -->|A2A Protobuf| B[Agent Server]
        B -->|SSE Stream| C[Network Byte-stream]
    end

    subgraph "Frontend (Angular Chat-UI)"
        C -->|Raw EventSource| D[A2aService]
        D -->|Defensive Extraction| E[ChatMessage Object]
        E -->|a2uiPayload| F[MessageProcessor]
        F -->|Surface Map| G[A2uiSurfaceComponent]
        G -->|Recursive Rendering| H[Browser DOM]
    end

    subgraph "Feedback Loop"
        H -->|User Click| I[Action Dispatcher]
        I -->|POST /action| B
    end
```

## Component Hierarchy

How the custom recursive renderer decomposes the A2UI tree.

```mermaid
graph TD
    subgraph "Angular Component Tree"
        App[App Component] --> MsgList[Message List]
        MsgList --> MsgBubble[Message Bubble]
        MsgBubble --> Renderer[A2uiSurfaceComponent]
    end

    subgraph "A2UI Recursive Node Processing"
        Renderer -->|If Node is Layout| Recurse[Call Template Again]
        Recurse --> Child[Child Node]
        Renderer -->|If Node is Leaf| Leaf[Render Specific Primitive]
        Leaf --> Text[Text Node]
        Leaf --> Img[Image Node]
        Leaf --> Btn[Button Node]
    end
```

## State Machine: Rendering Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    Disconnected --> Listening: Connect to SSE
    Listening --> BeginRendering: Receive beginRendering
    BeginRendering --> SurfaceInitialized: Create Surface ID in Map
    SurfaceInitialized --> ProcessingUpdates: Receive surfaceUpdate
    ProcessingUpdates --> ProcessingUpdates: Incremental Data Bindings
    ProcessingUpdates --> Rendered: Final Root Node Attached
    Rendered --> ProcessingUpdates: Live Generative Updates
```
