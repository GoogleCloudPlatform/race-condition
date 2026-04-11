alloydb-proxy: bash scripts/core/start_db.sh
gateway: PORT=$GATEWAY_PORT go run cmd/gateway/main.go
simulator: PORT=$SIMULATOR_PORT DISPATCH_MODE=callable .venv/bin/python3 agents/simulator/agent.py
simulator-with-failure: PORT=$SIMULATOR_WITH_FAILURE_PORT DISPATCH_MODE=callable .venv/bin/python3 agents/simulator_with_failure/agent.py
planner: PORT=$PLANNER_PORT DISPATCH_MODE=callable .venv/bin/python3 agents/planner/agent.py
planner_with_eval: PORT=$PLANNER_WITH_EVAL_PORT DISPATCH_MODE=callable .venv/bin/python3 agents/planner_with_eval/agent.py
planner_with_memory: PORT=$PLANNER_WITH_MEMORY_PORT DISPATCH_MODE=callable .venv/bin/python3 agents/planner_with_memory/agent.py
dash: PORT=$DASH_PORT .venv/bin/python3 scripts/core/agent_dash.py
tester: PORT=$TESTER_PORT go run cmd/tester/main.go
admin: PORT=$ADMIN_PORT go run cmd/admin/main.go
runner: PORT=$RUNNER_PORT DISPATCH_MODE=subscriber .venv/bin/python3 agents/npc/runner/agent.py
runner_autopilot: PORT=$RUNNER_AUTOPILOT_PORT DISPATCH_MODE=subscriber .venv/bin/python3 agents/npc/runner_autopilot/agent.py
frontend: PORT=$FRONTEND_BFF_PORT GATEWAY_INTERNAL_URL=http://localhost:$GATEWAY_PORT FRONTEND_DEV_URL=http://localhost:$FRONTEND_APP_PORT go run cmd/frontend/main.go
frontend-app: cd web/frontend && npm start
