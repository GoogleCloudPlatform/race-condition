# Distributed Switchboard | Tester UI

The Tester UI is a developer-facing tool used to verify the Distributed
Switchboard and the A2UI (Agent-to-UI) protocol.

## Features

- **Agent Discovery**: Real-time listing of registered simulation agents.
- **Session Control**: Manual spawning and lifecycle management of agent
  sessions.
- **Session Color Coding**: Visual grouping of log entries and response cards
  using session-specific colors.
- **Rich Markdown Logs**: High-quality rich text rendering for all agent
  narratives and pulses.
- **Targeted Messaging**: Multi-session broadcast fan-out logic directly from
  the UI.

## Getting Started

```bash
npm install
npm run dev -- --port 8304
```

## Testing Protocol

The project uses **Vitest** for unit and component testing, ensuring the
rendering engine is stable.

```bash
# Run all tests
npm test

# Watch mode
npm run test:watch
```

### Coverage Highlights

- **Rendering Engine**: Maps A2UI types (Video, Choice, etc.) to DOM renderers.
- **Component Templates**: Individual validation for each A2UI primitive
  (Choice, Video, Image, Notification).
- **API Integration**: Mocked interactions with the Gateway discovery and
  session APIs.

## Architecture

- **`src/a2ui/index.ts`**: Core rendering engine that maps A2UI types to
  component renderers.
- **`src/a2ui/components/`**: Atomic renderers for each A2UI primitive.

