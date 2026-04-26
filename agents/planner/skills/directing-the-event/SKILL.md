---
name: directing-the-event
description: >
  Use when the marathon plan needs non-spatial event parameters defined:
  theme, hydration-point logistics, crowd zones, start times, or
  expected participant counts. Triggered when the request describes the
  feel or operational logistics of the race rather than its physical
  route.
license: Apache-2.0
metadata:
  adk_additional_tools:
    - plan_marathon_event
---

# Directing the Event

You use this skill to define the "soul" and logistics of the marathon.

## Instructions

1. **Characteristics**: Define the theme, hydration points, and crowd zones.
2. **Logistics**: Set start times and expected participant counts.

## Tools

- `plan_marathon_event(requirements, tool_context)`: Define event parameters.
