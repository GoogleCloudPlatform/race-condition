---
name: hydration
description:
  Hydration management for the runner, tracking water depletion and
  rehydration stations.
---

# Hydration Management

The runner starts the race partially hydrated (typically 88-100, ability-correlated). Water depletes over distance and affects performance.

## Instructions

1. **Deplete Hydration**: When you receive a distance update, call `deplete_water` to reduce your hydration based on how far you ran:
   - Base loss: ~3.2 per mile (scaled by runner ability).
   - Fatigue growth rate: ~3.2% per mile of total distance run.
2. **Rehydrate at Stations**: When you enter a hydration station, decide whether to call `rehydrate` based on your current hydration:
   - Hydration <= 40: always stop.
   - Hydration 41-60: stop ~50% of the time.
   - Hydration > 60: stop ~30% of the time.
   - If **exhausted**: always stop.
3. **Avoid Collapse**: If hydration drops below 30, you become **exhausted**. If it drops below 10 while exhausted, you **collapse** and cannot continue.

## Tools

- `deplete_water`: Deplete hydration by the given amount. Tracks exhaustion and collapse automatically.
- `rehydrate`: Rehydrate at a station (capped at 100).

**Note: Call these tools directly (no prefix like "hydration:").**
