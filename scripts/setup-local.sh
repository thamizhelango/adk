#!/bin/bash
# Local development setup script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== ADK Local Development Setup ==="
echo ""

# Check prerequisites
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "ERROR: $1 is required but not installed."
        exit 1
    fi
}

echo "Checking prerequisites..."
check_command kubectl
check_command python3
check_command docker

# Check if we have a Kubernetes cluster
if ! kubectl cluster-info &> /dev/null; then
    echo ""
    echo "WARNING: No Kubernetes cluster found."
    echo "You can create one with:"
    echo "  - minikube start"
    echo "  - kind create cluster"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create Python virtual environment
echo ""
echo "Setting up Python environment..."
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "Installing CRDs..."
kubectl apply -f k8s/crds/

echo ""
echo "Creating namespace..."
kubectl apply -f k8s/controller/namespace.yaml || true

echo ""
echo "Setting up RBAC..."
kubectl apply -f k8s/controller/rbac.yaml

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To run the controller locally:"
echo "  cd $PROJECT_DIR"
echo "  source venv/bin/activate"
echo "  python -m controller.main"
echo ""
echo "To deploy the mock vLLM (for testing without GPU):"
echo "  kubectl apply -f k8s/vllm-mock/"
echo ""
echo "To create an example agent:"
echo "  kubectl apply -f examples/sre-agent.yaml"
echo ""
echo "To submit a task:"
echo "  kubectl apply -f examples/sample-task.yaml"
echo ""
echo "To watch runs:"
echo "  kubectl get agentruns -w"
