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

# install_alloydb_proxy.sh — Downloads the AlloyDB Auth Proxy binary.
#
# Usage:
#   bash scripts/core/install_alloydb_proxy.sh
#
# Places the binary at ./alloydb-auth-proxy in the project root.
# Run once; the Procfile entry will use it automatically.

set -euo pipefail

DEST="./alloydb-auth-proxy"
BASE_URL="https://storage.googleapis.com/alloydb-auth-proxy"

# Determine latest version
VERSION="v1.13.1"

# Detect OS and architecture
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    case "$ARCH" in
      arm64)  BINARY="alloydb-auth-proxy.darwin.arm64" ;;
      x86_64) BINARY="alloydb-auth-proxy.darwin.amd64" ;;
      *)      echo "Unsupported macOS arch: $ARCH" && exit 1 ;;
    esac
    ;;
  Linux)
    case "$ARCH" in
      x86_64)  BINARY="alloydb-auth-proxy.linux.amd64" ;;
      aarch64) BINARY="alloydb-auth-proxy.linux.arm64" ;;
      *)       echo "Unsupported Linux arch: $ARCH" && exit 1 ;;
    esac
    ;;
  *)
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

URL="${BASE_URL}/${VERSION}/${BINARY}"

echo "Downloading AlloyDB Auth Proxy ${VERSION} for ${OS}/${ARCH}..."
echo "  => ${URL}"
curl -sf -o "$DEST" "$URL"
chmod +x "$DEST"

echo ""
echo "✅ AlloyDB Auth Proxy installed at ${DEST}"
echo ""
echo "It will start automatically via 'uv run dev' (Procfile: alloydb-proxy)."
echo "Or run it manually:"
echo "  ./alloydb-auth-proxy \\"
echo "    'projects/your-gcp-project-id/locations/us-central1/clusters/am-cluster/instances/agent-memory' \\"
echo "    --public-ip --port=5433"
