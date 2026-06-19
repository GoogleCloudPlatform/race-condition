#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# ANSI escape codes for colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}      Race Condition macOS Setup Script        ${NC}"
echo -e "${BLUE}===============================================${NC}"

# 1. Check OS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}❌ Error: This script is intended for macOS only.${NC}"
    exit 1
fi

# 2. Add Homebrew path to current session just in case
if [[ $(uname -m) == "arm64" ]]; then
    export PATH="/opt/homebrew/bin:$PATH"
else
    export PATH="/usr/local/bin:$PATH"
fi

# 3. Check/Install Homebrew
if ! command -v brew >/dev/null 2>&1; then
    echo -e "${YELLOW}🍺 Homebrew not found. Installing Homebrew...${NC}"
    echo "This may require your password for administrator privileges."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Reload shellenv for the current script execution
    if [[ $(uname -m) == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    else
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo -e "${GREEN}✅ Homebrew is already installed.${NC}"
fi

# Helper function to install brew package if not present
install_brew_pkg() {
    local pkg=$1
    local cmd=$2
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo -e "${YELLOW}📦 Installing $pkg...${NC}"
        brew install "$pkg"
    else
        echo -e "${GREEN}✅ $pkg is already installed.${NC}"
    fi
}

# Helper function to install brew cask if command not present
install_brew_cask() {
    local cask=$1
    local cmd=$2
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo -e "${YELLOW}📦 Installing $cask (cask)...${NC}"
        brew install --cask "$cask"
    else
        echo -e "${GREEN}✅ $cask is already installed.${NC}"
    fi
}

# 4. Install standard packages
install_brew_pkg "go" "go"
install_brew_pkg "node" "node"
install_brew_pkg "uv" "uv"
install_brew_cask "google-cloud-sdk" "gcloud"
install_brew_cask "docker" "docker"

# 5. Handle Docker daemon startup
echo -e "${BLUE}🐳 Checking Docker daemon status...${NC}"
if ! docker info >/dev/null 2>&1; then
    echo -e "${YELLOW}🐳 Docker is not running. Launching Docker Desktop...${NC}"
    open -a Docker
    echo -e "${YELLOW}⏳ Waiting for Docker to start. Please accept the Docker Desktop terms if prompted...${NC}"
    
    # Wait loop
    local attempts=0
    local max_attempts=30 # Wait up to 2.5 minutes
    until docker info >/dev/null 2>&1; do
        if [ $attempts -ge $max_attempts ]; then
            echo -e "${RED}❌ Timeout waiting for Docker to start.${NC}"
            echo -e "${YELLOW}Please start Docker Desktop manually from your Applications folder and press ENTER to continue...${NC}"
            read -r
            attempts=0 # Reset wait timer
        fi
        sleep 5
        attempts=$((attempts + 1))
        echo "   Waiting for Docker daemon... ($((attempts * 5))s)"
    done
    echo -e "${GREEN}✅ Docker is running.${NC}"
else
    echo -e "${GREEN}✅ Docker is already running.${NC}"
fi

# 6. Configure environment (.env)
if [ ! -f .env ]; then
    echo -e "${YELLOW}📋 Creating .env from .env.example...${NC}"
    cp .env.example .env
else
    echo -e "${GREEN}✅ .env already exists.${NC}"
fi

# 7. GCP Vertex AI setup (Interactive & Optional)
echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}          Google Cloud / Gemini Setup          ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo "By default, Race Condition uses GCP Vertex AI for Gemini API calls."
echo "Do you want to configure GCP authentication now? (y/n)"
read -r response

if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo -n "Enter your Google Cloud Project ID: "
    read -r gcp_project
    
    if [ -z "$gcp_project" ]; then
        echo -e "${RED}❌ Project ID cannot be empty. Skipping GCP configuration...${NC}"
    else
        echo -e "${YELLOW}🔑 Authenticating with gcloud (a browser window will open)...${NC}"
        gcloud auth login --update-adc
        
        echo -e "${YELLOW}⚙️ Setting default project to $gcp_project...${NC}"
        gcloud config set project "$gcp_project"
        
        echo -e "${YELLOW}⚙️ Setting application default credentials quota project to $gcp_project...${NC}"
        gcloud auth application-default set-quota-project "$gcp_project"
        
        echo -e "${YELLOW}🔌 Enabling required APIs on Google Cloud (this may take a minute)...${NC}"
        gcloud services enable \
          aiplatform.googleapis.com \
          generativelanguage.googleapis.com \
          cloudresourcemanager.googleapis.com \
          pubsub.googleapis.com \
          iam.googleapis.com
        
        echo -e "${YELLOW}✍️ Updating project ID in .env...${NC}"
        sed -i '' "s/your-gcp-project-id/$gcp_project/g" .env
        
        echo -e "${GREEN}✅ GCP Vertex AI integration configured successfully.${NC}"
    fi
else
    echo -e "${YELLOW}⚠️ Skipping GCP authentication config.${NC}"
    echo "Note: The LLM agents will fail to run unless you either:"
    echo "  1) Run 'gcloud auth login --update-adc' and set PROJECT_ID in .env later."
    echo "  2) Set RUNNER_MODEL=ollama_chat/gemma4:e2b in .env to use a local Ollama instance."
    echo "  3) Use the deterministic autopilot runner (which makes zero LLM calls)."
fi

# 8. Project initialization
echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}         Initializing Project (make init)      ${NC}"
echo -e "${BLUE}===============================================${NC}"
make init

# 9. Verify Installation
echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}             Verifying Installation            ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo "Running offline Go and Python unit tests..."
if make test-unit-go test-py; then
    echo -e "${GREEN}✅ All verification unit tests passed successfully!${NC}"
else
    echo -e "${RED}❌ Some verification tests failed. Please review the output above.${NC}"
    exit 1
fi

echo -e "${BLUE}===============================================${NC}"
echo -e "${GREEN}🎉 Setup Completed Successfully!${NC}"
echo -e "${BLUE}===============================================${NC}"
echo "To start the simulation, run:"
echo -e "${GREEN}  make start${NC}"
echo ""
echo "Once started, you can access:"
echo "  - Frontend (3D UI): http://localhost:9119"
echo "  - Admin Dashboard: http://localhost:9100"
echo "  - Tester UI:  http://localhost:9112"
echo "==============================================="
