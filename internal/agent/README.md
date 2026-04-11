# Agent Package

The `agent` package provides the core registration and discovery mechanisms for
simulation entities.

## Role

- **Catalog Management**: Maintains a registry of available agent types and
  their capabilities.
- **Service Discovery**: Allows components to look up agents by role or
  capability.
- **Metadata Handling**: Manages agent-specific configuration and status.

## Key Components

- `catalog.go`: Implementation of the agent service catalog.
- `registry.go`: Management of A2A endpoints and capability sets.
