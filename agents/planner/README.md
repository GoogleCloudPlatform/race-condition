# Planner Agent

ADK-powered GIS analyst for marathon route planning and event logistics.

## Overview

The Planner Agent uses the Google Agent Development Kit (ADK) with Gemini 3
Flash to generate mathematically precise 26.2-mile marathon routes. It leverages
built-in GIS data (`network.json`) for the Las Vegas road network and applies
best practices for route design, including landmark sequencing, spectator
engagement, and logistical efficiency.

## Configuration

| Variable                | Required | Default  | Description       |
| :---------------------- | :------- | :------- | :---------------- |
| `PORT` / `PLANNER_PORT` | No       | `8204`   | HTTP listen port  |
| `GOOGLE_CLOUD_LOCATION` | No       | `global` | Gemini API region |

## Running Locally

```bash
# Standalone
uv run python -m agents.planner.agent

# Via Honcho (recommended)
honcho start planner
```

## Skills

The Planner loads skills dynamically from `agents/planner/skills/`:

- **route_planning**: GIS-based marathon route generation using `networkx` and
  `osmnx`. Accepts a `theme_sequence` of landmark names and produces GeoJSON
  output with the route, water stations, and medical tents.

## API / Interface

| Method | Path                         | Description                |
| :----- | :--------------------------- | :------------------------- |
| `GET`  | `/health`                    | Basic health check         |
| `POST` | `/a2a/planner/orchestration` | A2A orchestration endpoint |

## Architecture

The Planner communicates with the simulation via the
`SimulationCommunicationPlugin` and is discoverable through the
`agents/catalog.json` registry. It receives planning requests from the
Orchestrator and emits A2UI surfaces for route visualization.
