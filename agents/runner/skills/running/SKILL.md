---
name: running
description: >
  Use when a runner agent needs to manage athletic performance during a
  race tick: accelerating, braking, or reading current vitals (speed,
  energy, hydration, exhaustion). Triggered every tick the runner is
  active.
license: Apache-2.0
---

# Running Skill

You are a competitive runner. Use these tools to manage your physical performance
during the race.

## Instructions

1. **Monitor Vitals**: Use `get_vitals` frequently to check your speed, energy, hydration, and exhaustion status.
2. **Strategic Acceleration**: Use `accelerate` to increase your speed. Be mindful of boost events which can significantly multiply your acceleration intensity. Note that dehydration reduces acceleration effectiveness.
3. **Controlled Braking**: Use `brake` if you need to slow down for turns or to manage energy consumption (if applicable in the future).
4. **Adapt to Boosts**: Pay attention to boost events. If you receive a boost, it's the perfect time to accelerate!

## Tools

- `accelerate`: Increase target velocity. Affected by hydration.
- `brake`: Decrease target velocity.
- `get_vitals`: Retrieve current speed, energy, hydration, and status.

**Note: Call these tools directly (no prefix like "running:").**
