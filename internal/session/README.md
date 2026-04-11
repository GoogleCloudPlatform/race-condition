# Session Management

The `session` package handles global session state and registry, enabling
multi-tenant simulation tracking.

## Role

- **Session Registry**: Tracks active simulation sessions and their associated
  metadata.
- **Redis Integration**: Provides a distributed session store for horizontal
  scalability.
- **Lifecycle Management**: Handles session creation, expiration, and cleanup.

## Key Types

- `Registry` — Interface for session tracking operations
- `RedisRegistry` — Redis-backed implementation using sorted sets for session
  TTL management
- `Session` — Metadata about an active simulation session (ID, agent type,
  creation time)

## Configuration

| Variable     | Required | Default | Description               |
| :----------- | :------- | :------ | :------------------------ |
| `REDIS_ADDR` | Yes      | —       | Redis address for storage |

## Key Files

- `service.go`: Core session logic, `Registry` interface definition
- `redis_registry.go`: Redis-backed implementation with `TrackSession`,
  `UntrackSession`, `GetActiveSessions`
