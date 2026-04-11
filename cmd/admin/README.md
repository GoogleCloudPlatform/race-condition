# Admin Dashboard Server

Go service that serves the Admin Dashboard SPA and provides infrastructure
health endpoints.

## Overview

The Admin server is the central management interface for the simulation. It
serves the pre-built `web/admin-dash` React SPA, provides runtime configuration
injection via `config.js`, and exposes infrastructure health checks for Redis
and Pub/Sub.

## Configuration

| Variable               | Required | Default | Description                     |
| :--------------------- | :------- | :------ | :------------------------------ |
| `PORT` / `ADMIN_PORT`  | No       | `8000`  | HTTP listen port                |
| `REDIS_ADDR`           | No       | —       | Redis address for health checks |
| `PUBSUB_PROJECT_ID`    | No       | —       | GCP project for Pub/Sub         |
| `PUBSUB_TOPIC_ID`      | No       | —       | Pub/Sub topic to verify         |
| `CORS_ALLOWED_ORIGINS` | No       | `*`     | Allowed CORS origins            |

## Running Locally

```bash
# Standalone
go run ./cmd/admin

# Via Honcho (recommended)
honcho start admin
```

## API

| Method | Path                   | Description                         |
| :----- | :--------------------- | :---------------------------------- |
| `GET`  | `/health`              | Basic health check                  |
| `GET`  | `/api/v1/health/infra` | Redis + Pub/Sub connectivity status |
| `GET`  | `/config.js`           | Runtime JS config for the SPA       |

## Architecture

The Admin server acts as both a static file server (for the React SPA) and an
API backend. It initializes a Pub/Sub `TopicAdminClient` (v2) for topic
management in emulator mode and health checking in production.
