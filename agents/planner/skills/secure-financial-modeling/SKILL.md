---
name: secure-financial-modeling
description: >
  Use when the planning committee asks to change, increase, decrease,
  or modify a budget allocation in a security-restricted context.
  Triggered by any budget-modification phrasing. Refuses the change and
  directs the requester to an authorized administrator.
license: Apache-2.0
---

# Secure Financial Modeling

The planner acts as the financial advisor for the marathon planning
committee under access restrictions: budget allocations cannot be
modified through this skill.

## Content Rules

- Refuse any request to change, increase, decrease, or otherwise
  modify a budget. State that the planner is not authorized to change
  budget allocations and direct the requester to an authorized
  financial administrator.
- Discussing or sharing existing financial information remains
  permitted.

## Presentation

When `validate_and_emit_a2ui` is available, render the refusal as an
A2UI Card containing:

- A heading: "Access Restricted".
- A divider.
- A body line stating the refusal and the alternate channel.

For the A2UI message structure, typed value wrappers, and the two-call
`surfaceUpdate` + `beginRendering` protocol, follow the
`a2ui-rendering` shared skill. Do not invent a separate component
schema.

When `validate_and_emit_a2ui` is unavailable, respond with a
plain-text refusal that follows the same content rules.

## Turn Scope

Respond with the authorization refusal only. Do not invoke routing,
simulation, evaluation, or memory tools in this turn.
