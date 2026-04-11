#!/bin/bash
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

set -e

echo "🔨 Generating Protobuf bindings..."

# 1. Go Generation
# Requires: protoc-gen-go
if ! command -v protoc-gen-go &> /dev/null; then
    echo "⚠️  Warning: protoc-gen-go not found. Skipping Go generation."
    echo "   To install: go install google.golang.org/protobuf/cmd/protoc-gen-go@latest"
else
    protoc --go_out=. --go_opt=paths=source_relative gen_proto/gateway/gateway.proto
    # 2. Go Module Tidy (Ensures gen_proto is correctly indexed)
    echo "🐹 Go: Tidying module graph..."
    go mod tidy
    echo "✅ Generated Go bindings"
fi

# 2. Python Generation
# CRITICAL: Only use grpc_tools.protoc from the project venv.
# The system protoc (Homebrew) may generate code requiring protobuf >= 7.0,
# which is incompatible with google-cloud-aiplatform and grpcio-tools
# (both capped at protobuf < 7.0). Falling back to system protoc silently
# generates incompatible code that crashes at import time with:
#   VersionError: gencode 7.x runtime 6.x
VENV_PYTHON=".venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Error: Python venv not found at .venv/bin/python3"
    echo "   Run 'uv sync' to create the venv before generating protos."
    exit 1
fi

if $VENV_PYTHON -c "import grpc_tools" &> /dev/null; then
    $VENV_PYTHON -m grpc_tools.protoc -I. --python_out=. --pyi_out=. gen_proto/gateway/gateway.proto
    echo "✅ Generated Python bindings (via grpc_tools)"
else
    echo "❌ Error: grpc_tools not found in venv."
    echo "   Run 'uv sync' to install dependencies before generating protos."
    echo "   System protoc ($(protoc --version 2>/dev/null || echo 'not found')) generates incompatible gencode."
    exit 1
fi

# Validate gencode version — must be < 7.0.0
GENCODE_MAJOR=$($VENV_PYTHON -c "
import re, sys
with open('gen_proto/gateway/gateway_pb2.py') as f:
    content = f.read()
m = re.search(r'ValidateProtobufRuntimeVersion\(\s*\S+\s*,\s*(\d+)', content)
if m:
    print(m.group(1))
else:
    print('unknown')
    sys.exit(1)
")
if [ "$GENCODE_MAJOR" = "unknown" ]; then
    echo "❌ Error: Could not determine gencode version from gateway_pb2.py."
    echo "   The generated file may have an unexpected format."
    exit 1
fi
if [ "$GENCODE_MAJOR" -ge 7 ] 2>/dev/null; then
    echo "❌ Error: Generated gateway_pb2.py has gencode major version $GENCODE_MAJOR (>= 7)."
    echo "   This is incompatible with the protobuf runtime (< 7.0.0)."
    echo "   Check that grpc_tools.protoc is being used, not system protoc."
    rm -f gen_proto/gateway/gateway_pb2.py gen_proto/gateway/gateway_pb2.pyi
    exit 1
fi
echo "✅ Validated gencode version: $GENCODE_MAJOR.x (< 7.0.0)"

# 3. Web Sync
# Ensure the web tester has the latest proto definition
WEB_PROTO_PATH="web/tester/public/gateway.proto"
if [ -d "web/tester/public" ]; then
    cp gen_proto/gateway/gateway.proto "$WEB_PROTO_PATH"
    echo "✅ Synced proto to web/tester"
fi

echo "✨ Generation complete."
