#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# E2E Dispatch Mode Validation
# Validates subscriber vs callable routing with live gateway + mock agents.
#
# Prerequisites: docker-compose up -d (Redis on port 8102)
# Usage: bash scripts/e2e/e2e_dispatch_test.sh

set -euo pipefail

GATEWAY_PORT="${GATEWAY_PORT:-8101}"
MOCK_SUBSCRIBER_PORT=9901
MOCK_CALLABLE_PORT=9902
GATEWAY_PID=""
SUBSCRIBER_PID=""
CALLABLE_PID=""
PASS=0
FAIL=0

cleanup() {
  echo ""
  echo "🧹 Cleaning up..."
  [[ -n "$GATEWAY_PID" ]] && kill "$GATEWAY_PID" 2>/dev/null || true
  [[ -n "$SUBSCRIBER_PID" ]] && kill "$SUBSCRIBER_PID" 2>/dev/null || true
  [[ -n "$CALLABLE_PID" ]] && kill "$CALLABLE_PID" 2>/dev/null || true
  rm -f /tmp/subscriber_request.log /tmp/callable_request.log /tmp/gateway_e2e.log
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Results: ✅ $PASS passed, ❌ $FAIL failed"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if [[ $FAIL -gt 0 ]]; then
    exit 1
  fi
}
trap cleanup EXIT

assert_contains() {
  local label="$1"
  local file="$2"
  local pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ✅ $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $label (expected '$pattern' in $file)"
    echo "     File contents: $(cat "$file" 2>/dev/null || echo '<empty>')"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1"
  local file="$2"
  local pattern="$3"
  if ! grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ✅ $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $label (unexpected '$pattern' found in $file)"
    FAIL=$((FAIL + 1))
  fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  E2E Dispatch Mode Validation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- Step 1: Start mock subscriber agent (expects /a2a/runner/orchestration) ---
echo ""
echo "🏃 Step 1: Starting mock subscriber agent on :$MOCK_SUBSCRIBER_PORT..."
rm -f /tmp/subscriber_request.log
python3 -c "
import http.server, json, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        with open('/tmp/subscriber_request.log', 'a') as f:
            f.write(f'PATH={self.path}\n')
            f.write(f'BODY={body}\n')
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args): pass

http.server.HTTPServer(('127.0.0.1', $MOCK_SUBSCRIBER_PORT), Handler).serve_forever()
" &
SUBSCRIBER_PID=$!
sleep 1

# --- Step 2: Start mock callable agent (expects A2A message/send) ---
echo "🤖 Step 2: Starting mock callable agent on :$MOCK_CALLABLE_PORT..."
rm -f /tmp/callable_request.log
python3 -c "
import http.server, json, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        with open('/tmp/callable_request.log', 'a') as f:
            f.write(f'PATH={self.path}\n')
            f.write(f'BODY={body}\n')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        resp = json.dumps({'jsonrpc':'2.0','id':'1','result':{'kind':'task','id':'t1','context_id':'c1','status':{'state':'completed'}}})
        self.wfile.write(resp.encode())
    def log_message(self, *args): pass

http.server.HTTPServer(('127.0.0.1', $MOCK_CALLABLE_PORT), Handler).serve_forever()
" &
CALLABLE_PID=$!
sleep 1

# --- Step 3: Start gateway with URL env vars pointing to mock agents ---
# The gateway reads agents/catalog.json which uses ${VAR} template URLs.
# We set the env vars so catalog URLs resolve to our mock agents.
echo "🌐 Step 3: Starting gateway on :$GATEWAY_PORT..."

# Point catalog URLs to mock agents
export RUNNER_INTERNAL_URL="http://127.0.0.1:$MOCK_SUBSCRIBER_PORT"
export SIMULATOR_INTERNAL_URL="http://127.0.0.1:$MOCK_CALLABLE_PORT"
export PLANNER_URL="http://127.0.0.1:19999"  # Not running, will fail silently
export REDIS_ADDR="localhost:8102"
export PORT=$GATEWAY_PORT

go run cmd/gateway/main.go > /tmp/gateway_e2e.log 2>&1 &
GATEWAY_PID=$!
echo "   Waiting for gateway to start..."
sleep 4

# Verify gateway started
if ! curl -s "http://127.0.0.1:$GATEWAY_PORT/healthz" > /dev/null 2>&1; then
  echo "  ❌ Gateway failed to start! Check /tmp/gateway_e2e.log"
  cat /tmp/gateway_e2e.log | head -20
  exit 1
fi
echo "   Gateway is running ✓"

# --- Step 4: Send push event for subscriber agent (runner) ---
echo ""
echo "📡 Step 4: Testing subscriber dispatch (runner)..."
# base64 of: {"agentType": "runner", "sessionId": "e2e-sub-1"}
curl -s -X POST "http://127.0.0.1:$GATEWAY_PORT/api/v1/orchestration/push" \
  -H "Content-Type: application/json" \
  -d '{"message":{"data":"eyJhZ2VudFR5cGUiOiAicnVubmVyIiwgInNlc3Npb25JZCI6ICJlMmUtc3ViLTEifQ=="}}' \
  > /dev/null 2>&1
sleep 3

assert_contains "Subscriber received request" /tmp/subscriber_request.log "PATH=/a2a/runner/orchestration"
assert_contains "Subscriber received raw JSON body" /tmp/subscriber_request.log "agentType"
assert_not_contains "Subscriber did NOT receive JSON-RPC" /tmp/subscriber_request.log "message/send"

# --- Step 5: Send push event for callable agent (simulator) ---
echo ""
echo "📡 Step 5: Testing callable dispatch (simulator)..."
# base64 of: {"agentType": "simulator", "sessionId": "e2e-call-1"}
curl -s -X POST "http://127.0.0.1:$GATEWAY_PORT/api/v1/orchestration/push" \
  -H "Content-Type: application/json" \
  -d '{"message":{"data":"eyJhZ2VudFR5cGUiOiAic2ltdWxhdG9yIiwgInNlc3Npb25JZCI6ICJlMmUtY2FsbC0xIn0="}}' \
  > /dev/null 2>&1
sleep 3

assert_contains "Callable received request" /tmp/callable_request.log "PATH=/"
assert_contains "Callable received JSON-RPC 2.0" /tmp/callable_request.log "jsonrpc"
assert_contains "Callable received message/send method" /tmp/callable_request.log "message/send"
assert_not_contains "Callable did NOT receive /orchestration path" /tmp/callable_request.log "/orchestration"

echo ""
echo "📋 Gateway dispatch log:"
grep -E "Switchboard:|ORCHESTRATION_PUSH:" /tmp/gateway_e2e.log | head -15

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
