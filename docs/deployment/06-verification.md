# Verification and Troubleshooting

This guide covers post-deployment verification: health checks, smoke tests, and
troubleshooting. Run through these checks after completing guides 01--05 to
confirm your deployment is fully operational.

## 1. Service Health Checks

Every service exposes a `/health` endpoint that returns a JSON body with
`{"status": "ok"}` and a `200 OK` status code. The gateway additionally reports
infrastructure status (Redis, Pub/Sub connectivity).

### Cloud Run Services

| Service        | Health URL                                           | Expected Response Body                                                 |
| :------------- | :--------------------------------------------------- | :--------------------------------------------------------------------- |
| **gateway**    | `https://gateway.{env}.{domain}/health`              | `{"status":"ok","service":"gateway","infra":{"redis":"online","pubsub":"online"}}` |
| **admin**      | `https://admin.{env}.{domain}/health`                | `{"status":"ok","service":"admin"}`                                    |
| **tester**     | `https://tester.{env}.{domain}/health`               | `{"status":"ok","service":"tester"}`                                   |
| **frontend**   | Use `.run.app` URL (not behind LB by default)        | `{"status":"ok","service":"frontend"}`                                 |
| **dash**       | `https://dash.{env}.{domain}/health`                 | `{"status":"ok","service":"agent_dash"}`                               |

> **IAP Note:** If IAP is enabled, `curl` requests to custom domain URLs will
> receive `302` redirects. To test health with IAP enabled, use:
> ```bash
> curl -sS -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
>   https://gateway.YOUR-ENV.YOUR-DOMAIN/health
> ```

### Agent Engine Agents

Agent Engine agents do not expose Cloud Run--style health endpoints. Verify them
using the Vertex AI SDK or `gcloud`:

```bash
gcloud ai reasoning-engines list \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --format="table(name, displayName, createTime)"
```

### Quick Health Check Script

Test all Cloud Run services in one pass:

```bash
#!/usr/bin/env bash
# Usage: ./check-health.sh YOUR-ENV YOUR-DOMAIN

ENV="${1:-dev}"
DOMAIN="${2:-YOUR-DOMAIN}"

SERVICES=(gateway admin tester dash)

for svc in "${SERVICES[@]}"; do
  url="https://${svc}.${ENV}.${DOMAIN}/health"
  code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "  [OK]   ${svc} → ${code}"
  else
    echo "  [FAIL] ${svc} → ${code}"
  fi
done
```

To test a single service:

```bash
curl -sS https://gateway.YOUR-ENV.YOUR-DOMAIN/health | python3 -m json.tool
```

## 2. Automated Verification

The deployment script includes a `--verify` flag that checks service health
after deployment:

```bash
python scripts/deploy/deploy.py gateway --env dev --verify
```

### What `--verify` does

When `--verify` is passed, `deploy.py` calls `verify_health()` after
`deploy_service()` completes. For Cloud Run services, this:

1. Prints the expected health URL: `https://{service}.{env}.{domain}/health`
2. Runs `gcloud run services describe {service}` to confirm the service exists,
   its latest revision is serving traffic, and its configuration is correct

For Agent Engine (`reasoning-engine`) services, the verify step prints a
confirmation that the service type does not use Cloud Run health checks and
skips the probe.

### Verify all services at once

```bash
python scripts/deploy/deploy.py all --env dev --verify
```

This deploys every service defined in the `SERVICES` dictionary and runs
`verify_health()` on each one sequentially.

## 3. WebSocket Connectivity Test

The gateway uses **binary WebSocket frames** (protobuf-encoded `Wrapper`
messages), not text/JSON frames. Test connectivity with `wscat`:

```bash
# Install wscat if needed
npm install -g wscat

# Connect to the gateway WebSocket endpoint
wscat -c "wss://gateway.YOUR-ENV.YOUR-DOMAIN/ws?sessionId=test-verify"
```

**Expected behavior:**

- Connection is established (you see the `Connected` prompt)
- No immediate data -- the gateway only sends frames when agents produce events
- If agents are active, you will receive binary frames (displayed as hex in
  `wscat`)
- The connection should remain open indefinitely
- **Important:** The default Terraform configuration sets backend service
  timeout to 30s, which will disconnect idle WebSocket connections. For
  long-lived WebSocket connections, update the gateway backend service timeout
  to 3600s in `iap.tf` (add `timeout_sec = 3600` to the gateway backend
  service resource)

> **Note:** If IAP is enabled, direct WebSocket connections from the command
> line will fail with `403`. Use the tester UI which proxies WebSocket
> connections through its BFF layer, attaching OIDC tokens automatically.

### Testing through the tester BFF

The tester proxies WebSocket connections to the gateway with OIDC
authentication. This is the recommended way to verify WebSocket connectivity in
IAP-protected environments:

1. Open `https://tester.YOUR-ENV.YOUR-DOMAIN` in your browser
2. Open browser DevTools, go to the **Network** tab, and filter by **WS**
3. You should see a WebSocket connection to `/ws` in `Connected` state
4. When agents are active, binary frames will appear in the Messages panel

## 4. Agent Spawning Smoke Test

Verify that the gateway can discover agents and spawn sessions:

### Step 1: Check agent discovery

```bash
curl -sS https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/agent-types \
  | python3 -m json.tool
```

**Expected:** A JSON object mapping agent type names to their agent cards. Each
entry contains the agent's name, description, URL, and capabilities. If this
returns an error, check the gateway's `AGENT_URLS` environment variable.

### Step 2: Spawn an agent session

```bash
curl -sS -X POST https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/spawn \
  -H "Content-Type: application/json" \
  -d '{"agents": [{"agentType": "runner_autopilot", "count": 1}]}' \
  | python3 -m json.tool
```

**Expected response:**

```json
{
  "sessions": [
    {
      "sessionId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "agentType": "runner_autopilot"
    }
  ]
}
```

The gateway:

1. Validates the agent type against the catalog (calls `/api/v1/agent-types`
   internally)
2. Generates a UUID for the session
3. Registers the session in the Redis-backed distributed registry
4. Sends a `spawn_agent` event to the agent via the switchboard (poke +
   orchestration queue)
5. Returns the session ID(s) immediately (spawning is asynchronous)

### Step 3: Verify the session was registered

```bash
curl -sS https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/sessions \
  | python3 -m json.tool
```

The spawned session should appear in the list.

### Step 4: Verify via WebSocket

Connect via the tester UI and confirm binary protobuf frames begin arriving
after the agent starts processing.

## 5. End-to-End Verification Checklist

Use this checklist to confirm a complete, working deployment:

### Infrastructure

- [ ] Redis (Memorystore) instance is running and reachable from VPC
- [ ] Pub/Sub topics exist (`agent-telemetry`, `specialist-orchestration`)
- [ ] VPC connector is active and attached to all Cloud Run services
- [ ] Artifact Registry repository (`cloudrun`) contains all service images

### Cloud Run Services

- [ ] All 7 Cloud Run services are healthy (`/health` returns `200`)
- [ ] Gateway reports `redis: "online"` and `pubsub: "online"` in health
      response
- [ ] All services have `min-instances: 1` (no cold start for first request)

### Agent Engine

- [ ] All 7 Agent Engine agents created (`gcloud ai reasoning-engines list`)
- [ ] Gateway `AGENT_URLS` includes all Agent Engine A2A endpoint URLs
- [ ] Agent discovery returns all expected agent types
      (`/api/v1/agent-types`)

### Networking

- [ ] DNS records resolve correctly (`dig gateway.dev.example.com`)
- [ ] SSL certificates are `ACTIVE` (not `PROVISIONING`)
- [ ] Global load balancer routes to correct backend services
- [ ] WebSocket connections work through the load balancer (increase gateway backend timeout to 3600s in `iap.tf`)

### Authentication

- [ ] IAP is enabled on the load balancer backend services
- [ ] Authorized users can access the admin dashboard
- [ ] IAP returns `403` for unauthorized users
- [ ] Service-to-service calls use OIDC tokens (no IAP for internal traffic)

### Application

- [ ] Agent spawn succeeds via `/api/v1/spawn`
- [ ] WebSocket receives binary protobuf frames when agents are active
- [ ] Frontend loads 3D viewport (check browser console for errors)
- [ ] Admin dashboard shows all services with "online" status

## 6. Troubleshooting

### Common Issues

| Symptom | Likely Cause | Diagnostic Command | Fix |
| :--- | :--- | :--- | :--- |
| Cloud Run service won't start | Missing or invalid env vars | `gcloud run services logs read SERVICE --project=PROJECT --region=REGION --limit=50` | Check `build_env_vars()` in `deploy.py`; verify `.env.{env}` file |
| Gateway health shows `redis: "offline"` | Redis unreachable from VPC | `gcloud redis instances describe INSTANCE --region=REGION` | Verify VPC connector and `REDIS_ADDR` env var |
| Gateway health shows `pubsub: "offline"` | Pub/Sub emulator host unreachable | Check `PUBSUB_EMULATOR_HOST` env var | In cloud, remove `PUBSUB_EMULATOR_HOST`; Pub/Sub uses real API |
| Agent Engine deploy fails | Staging too large or import error | Check `deploy.py` output for traceback | Verify `_staging_ignore` filters; check `DISPATCH_MODE=callable` |
| Agent Engine deploy hangs | PSC network attachment missing | `gcloud compute network-attachments list --region=REGION` | Create `psc-re-attachment` network attachment |
| Redis connection refused | VPC connector misconfigured | `gcloud run services describe SERVICE --format='yaml(spec.template)'` | Verify `vpc-connector` annotation and `vpc-egress: all-traffic` |
| IAP returns 403 | User not in IAP access list | Console > Security > IAP | Add user/group to the IAP-secured backend service |
| DNS not resolving | NS records not delegated | `dig +trace gateway.dev.example.com` | Configure NS records at your domain registrar |
| SSL cert stuck `PROVISIONING` | DNS not pointing to LB IP | `gcloud compute ssl-certificates describe CERT_NAME` | Ensure DNS A records point to the load balancer's global IP |
| WebSocket disconnects after 30s | LB backend timeout too low (default 30s) | `gcloud compute backend-services describe BACKEND --global` | Add `timeout_sec = 3600` to gateway backend service in `iap.tf`, re-apply Terraform |
| Agents not discoverable | Missing `AGENT_URLS` on gateway | `gcloud run services describe gateway --format='yaml(spec.template.spec.containers[0].env)'` | Add Agent Engine A2A URLs to `AGENT_URLS`, redeploy gateway |
| Agent spawn returns unknown type | Agent card URL unreachable | `curl -sS AGENT_URL/.well-known/agent-card.json` | Verify agent is deployed and URL is correct in `AGENT_URLS` |
| Protobuf decode errors | Proto version mismatch | Check gateway logs for unmarshal errors | Rebuild proto bindings (`make proto`) and redeploy |
| Frontend blank white page | Asset loading failed | Browser DevTools console | Check CORS origins, verify `FRONTEND_URL` and `config.js` |
| Service-to-service 403 | OIDC token not attached | Check requesting service logs for "OIDC" errors | Verify `IAP_CLIENT_ID` is set on the calling service |

### Reading Cloud Run Logs

```bash
# Stream live logs
gcloud run services logs tail gateway \
  --project=YOUR_PROJECT_ID \
  --region=us-central1

# Read recent logs
gcloud run services logs read gateway \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --limit=100

# Filter for errors only
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=gateway \
  AND severity>=ERROR" \
  --project=YOUR_PROJECT_ID \
  --limit=50 \
  --format="table(timestamp, textPayload)"
```

### Checking Agent Engine Status

```bash
# List all deployed agents
gcloud ai reasoning-engines list \
  --project=YOUR_PROJECT_ID \
  --region=us-central1

# Describe a specific agent
gcloud ai reasoning-engines describe AGENT_ENGINE_ID \
  --project=YOUR_PROJECT_ID \
  --region=us-central1

# Check agent logs (via Cloud Logging)
gcloud logging read "resource.type=aiplatform.googleapis.com/ReasoningEngine" \
  --project=YOUR_PROJECT_ID \
  --limit=50
```

### Verifying VPC Connectivity

```bash
# Check VPC connector status
gcloud compute networks vpc-access connectors describe vpc-con-v2 \
  --project=YOUR_PROJECT_ID \
  --region=us-central1

# Verify a service is using the connector
gcloud run services describe gateway \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --format='value(spec.template.metadata.annotations."run.googleapis.com/vpc-access-connector")'

# Verify VPC egress setting
gcloud run services describe gateway \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --format='value(spec.template.metadata.annotations."run.googleapis.com/vpc-access-egress")'
```

### Verifying SSL and Load Balancer

```bash
# Check SSL certificate status (must be ACTIVE, not PROVISIONING)
gcloud compute ssl-certificates list \
  --project=YOUR_PROJECT_ID

# Check load balancer frontend IP
gcloud compute forwarding-rules list \
  --project=YOUR_PROJECT_ID \
  --global

# Verify DNS resolves to the LB IP
dig +short gateway.dev.example.com
```

### Nuclear Option: Flush and Re-Spawn

If the simulation is in a bad state (orphaned sessions, stuck agents), flush
all sessions and re-spawn:

```bash
# Flush all sessions from the distributed registry
curl -sS -X POST https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/sessions/flush

# Verify sessions are cleared
curl -sS https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/sessions

# Re-spawn agents
curl -sS -X POST https://gateway.YOUR-ENV.YOUR-DOMAIN/api/v1/spawn \
  -H "Content-Type: application/json" \
  -d '{"agents": [{"agentType": "runner_autopilot", "count": 2}, {"agentType": "simulator", "count": 1}]}'
```

---

**Previous:** [Domain & Auth](05-domain-and-auth.md) |
[Back to Index](README.md)
