# Admin Dashboard

React SPA for simulation management and infrastructure monitoring.

## Overview

The Admin Dashboard provides a centralized interface for managing the
simulation, monitoring infrastructure health (Redis, Pub/Sub), and navigating to
other service UIs. It is served by the `cmd/admin` Go server.

## Running Locally

```bash
cd web/admin-dash
npm install
npm run dev     # Development (Vite HMR)
npm run build   # Production bundle (served by cmd/admin)
```

## Features

- **Infrastructure Health**: Real-time Redis and Pub/Sub connectivity status
- **Service Navigation**: Links to all simulation UIs (Gateway, Tester,
  Visualizer, Agent Dash, Sidecar)
- **Runtime Config**: Dynamic configuration via `/config.js` endpoint
