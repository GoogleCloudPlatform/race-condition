# Entity Component System (ECS)

A high-performance Entity Component System implementation designed for real-time simulation logic.

## Architecture

The ECS separates data (Components) from logic (Systems).

- **Entities**: Unique identifiers for objects in the simulation.
- **Components**: Pure data structures attached to entities (e.g., `Position`, `Velocity`).
- **Systems**: Logic that operates on entities possessing specific component sets.
- **Engine**: The orchestrator that manages entity lifecycles and system execution loops.

## Usage

Systems are registered with the Engine and executed in a specific order during each simulation tick.

```go
engine := ecs.NewEngine()
engine.AddSystem(&MovementSystem{})
engine.Update(deltaTime)
```
