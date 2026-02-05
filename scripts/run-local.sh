#!/bin/bash
# Run the controller locally

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set environment variables for local development
export VLLM_ENDPOINT="${VLLM_ENDPOINT:-http://localhost:8000/v1}"
export USE_DOCKER_SANDBOX="${USE_DOCKER_SANDBOX:-true}"
export PYTHONPATH="$PROJECT_DIR"

echo "Starting ADK Controller..."
echo "  VLLM_ENDPOINT: $VLLM_ENDPOINT"
echo "  USE_DOCKER_SANDBOX: $USE_DOCKER_SANDBOX"
echo ""

python -m controller.main
