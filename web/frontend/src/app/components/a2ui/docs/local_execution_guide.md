# Local Execution Guide: Marathon Planning System

This guide explains how to run the **Marathon Planning Multi-Agent System**
entirely on your local machine.

## 🏗️ System Architecture (Unified Repository)

The system is a hub-and-spoke multi-agent orchestration. The project is now
consolidated into a single root repository, with the Angular frontend residing
in the `chat-ui` directory.

---

## 💻 Local Setup

### 1. Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- **GCP Project**: `your-gcp-project-id`
- **IAM Roles**: `roles/owner` or at minimum `roles/aiplatform.user`
- **Enabled APIs**:
  - `aiplatform.googleapis.com` (Vertex AI & Evaluation)
  - `reasoningengine.googleapis.com` (Agent Engine / A2A)
  - `run.googleapis.com` (Cloud Run)
  - `artifactregistry.googleapis.com` (Artifact Registry)

### 2. Environment Configuration

Create a `.env` file in the project root:

```bash
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
GOOGLE_CLOUD_LOCATION="global"
# Force Gemini to use Vertex AI routing
GOOGLE_GENAI_USE_VERTEXAI="true"

# Model defaults for local execution
TRAFFIC_PLANNER_MODEL="gemini-3-flash-preview"
COMMUNITY_PLANNER_MODEL="gemini-3-flash-preview"
ECONOMIC_PLANNER_MODEL="gemini-3-flash-preview"
MARATHON_PLANNER_MODEL="gemini-3-flash-preview"
EVENT_PLANNER_MODEL="gemini-3-flash-preview"

# Evaluator stays in us-central1 (Flash Lite)
EVALUATOR_MODEL="gemini-3-flash-lite-preview"
EVALUATOR_LOCATION="us-central1"

# Local mapping for orchestrator
TRAFFIC_PLANNER_AGENT_RESOURCE_NAME="local"
COMMUNITY_PLANNER_AGENT_RESOURCE_NAME="local"
ECONOMIC_PLANNER_AGENT_RESOURCE_NAME="local"
EVALUATOR_AGENT_RESOURCE_NAME="local"
```

### 3. Initialize Workspace

```bash
uv sync
gcloud auth application-default login
```

---

## 🚀 Running the System

### Step 1: Start All Agents (The Easy Way)

The project includes a `Procfile`. Since you have `honcho` installed, you can
start all 5 agents (Orchestrator + Specialists) with a single command:

```bash
honcho start -e .env
```

### Step 2: Start Agents Individually (The Manual Way)

If you prefer separate terminals, run these commands in order:

```bash
# Terminal 1: Traffic Planner
uv run python -m src.traffic_planner_agent.local_server

# Terminal 2: Community Planner
uv run python -m src.community_planner_agent.local_server

# Terminal 3: Economic Planner
uv run python -m src.economic_planner_agent.local_server

# Terminal 4: Evaluator Agent
uv run python -m src.evaluator_agent.local_server

# Terminal 5: Marathon Planner
uv run python -m src.marathon_planner_agent.local_server
```

---

## 🔍 Verification

Once all servers are running, you can verify they are alive by visiting the
Agent Card endpoints in your browser:

- **Marathon Planner**:
  [http://localhost:8084/.well-known/agent](http://localhost:8084/.well-known/agent)
- **Evaluator**:
  [http://localhost:8085/.well-known/agent](http://localhost:8085/.well-known/agent)
- **Traffic**:
  [http://localhost:8086/.well-known/agent](http://localhost:8086/.well-known/agent)
- **Community**:
  [http://localhost:8088/.well-known/agent-card.json](http://localhost:8088/.well-known/agent-card.json)
- **Economic**:
  [http://localhost:8087/.well-known/agent](http://localhost:8087/.well-known/agent)

## 💡 Pro Tip: Terminal Multiplexer

Since this requires 5 terminals, it's recommended to use a multiplexer like
`tmux` or the multi-pane feature in your IDE.
