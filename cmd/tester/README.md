# Tester BFF

Go server that hosts the [Tester UI](../../web/tester/) SPA and proxies all
WebSocket and REST traffic to the gateway. Same BFF pattern as the
[frontend BFF](../frontend/), but for the developer-facing test harness
instead of the production Angular app.

## What it does

The tester UI needs to connect to the gateway's binary protobuf WebSocket
and REST API. This BFF serves the compiled Vite app from the same origin as
those proxied endpoints, which eliminates CORS and keeps authentication
server-side.

Three responsibilities:

1. **Serve the SPA**: static files from `./web/tester/dist/` with SPA
   fallback routing
2. **Proxy WebSocket**: transparent binary frame forwarding to
   `GATEWAY_URL/ws` via
   [koding/websocketproxy](https://github.com/koding/websocketproxy)
3. **Proxy REST API**: forward all HTTP methods on `/api/v1/*` to the
   gateway, preserving query params, status, headers, and body

Both proxies strip `Authorization` and `x-goog-*` headers from outbound
requests and attach OIDC tokens for Cloud Run service-to-service auth.

## Dual mount points

Every route exists at both `/` and `/tester/` for Cloud Run GCLB path-based
routing:

```
/health            /tester/health
/config.js         /tester/config.js
/ws                /tester/ws
/api/v1/*          /tester/api/v1/*
```

`GET /tester` (no trailing slash) redirects to `/tester/`.

## Runtime configuration

`GET /config.js` returns:

```javascript
window.ENV = {
  "VITE_GATEWAY_URL": "/ws"
};
```

The relative `/ws` URL means the tester UI connects to its own origin for
WebSocket traffic. The BFF proxies it to the gateway transparently.

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` | `8080` | HTTP listen port (set to `8304` via `.env`) |
| `GATEWAY_INTERNAL_URL` | -- | Internal gateway URL (highest priority) |
| `GATEWAY_URL` | `http://localhost:8101` | Gateway URL (fallback) |
| `IAP_CLIENT_ID` | -- | OIDC audience for Cloud Run IAP auth |

## File layout

```
cmd/tester/
├── main.go       # Router, WS proxy, API proxy, static serving
└── main_test.go  # Health, config.js, WS frames, API proxy, header filtering
```

## Further reading

- The Tester UI frontend ([web/tester/](../../web/tester/)) contains the
  actual test harness logic (protobuf decoding, A2UI rendering)
- The frontend BFF ([cmd/frontend/](../frontend/)) uses the same pattern for
  the production Angular app
- The gateway ([cmd/gateway/](../gateway/)) is the upstream for all proxied
  traffic
