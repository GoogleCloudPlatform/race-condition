# A2UI Implementation Master Guide

## Overview

This guide serves as the authoritative resource for implementing Agent-to-Agent
(A2A) and Agent-to-User Interface (A2UI) capabilities in the Marathon Planner
ecosystem. It consolidates findings from the `a2ui-chat` project to ensure
protocol adherence, visual excellence, and generative UI compatibility.

## Documentation Suite

1. [Protocol & Stream Handling](file:///Users/caseywest/src/next26_dk_demo/docs/a2ui_protocol_and_streams.md)
   - Protocol & Stream Handling
   - Server-Sent Events (SSE) architecture.
   - The `msg.parts` vs `msg.content` discrepancy resolution.
   - Payload extraction best practices.

2. [Rendering Strategy & Generative UI Ethos](file:///Users/caseywest/src/next26_dk_demo/docs/a2ui_rendering_strategy.md)
   - Recursive `ng-template` pattern for nested A2UI nodes.
   - Canonical Catalog mapping (Strict Generative UI).
   - Rejecting non-standard custom primitives to maintain model compatibility.

3. [Visual Design System (Glassmorphism)](file:///Users/caseywest/src/next26_dk_demo/docs/a2ui_visual_design_system.md)
   - CSS tokens for "Gorgeous" UI (Blur, Borders, Shadows).
   - Primitive-level styling specs.

4. [Architecture Diagrams](file:///Users/caseywest/src/next26_dk_demo/docs/a2ui_architecture_diagrams.md)
   - Mermaid representations of data flow and component hierarchy.

## Key Principles

- **Generative First**: The UI must be able to render whatever the LLM generates
  using only Canonical A2UI primitives. Avoid specialized frontend widgets that
  the model doesn't "know" how to layout.
- **Defensive Parsing**: Always assume the stream payload might shift between
  SDK-suggested keys (`.content`) and wire-level keys (`.parts`).
- **High Fidelity**: Premium aesthetics (Glassmorphism) are not optional; they
  are the standard for A2UI interfaces.

---

_Created during the `a2ui-chat` debugging phase, March 2026._
