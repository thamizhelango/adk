# Agent Development Kit (ADK) - Working Implementation

A complete, working implementation of a self-hosted Agentic AI platform using Kubernetes, vLLM, and SPIFFE concepts.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                      │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │   CRDs      │    │ Controllers │    │  Execution  │      │
│  │             │    │             │    │             │      │
│  │ Agent       │───▶│ agent-ctrl  │───▶│ vLLM        │      │
│  │ AgentTask   │    │ task-ctrl   │    │ Sandbox     │      │
│  │ AgentRun    │    │ run-ctrl    │    │ Tools       │      │
│  └─────────────┘    └─────────────┘    └─────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Kubernetes cluster (minikube, kind, or real cluster)
- Python 3.11+
- Docker
- kubectl configured

### 1. Install CRDs

```bash
kubectl apply -f k8s/crds/
```

### 2. Deploy the Controller

```bash
# Build and deploy
docker build -t adk-controller:latest -f docker/Dockerfile.controller .
kubectl apply -f k8s/controller/
```

### 3. Deploy vLLM (or mock for testing)

```bash
# For testing without GPU, use the mock
kubectl apply -f k8s/vllm-mock/

# For real vLLM with GPU
kubectl apply -f k8s/vllm/
```

### 4. Create an Agent

```bash
kubectl apply -f examples/sre-agent.yaml
```

### 5. Submit a Task

```bash
kubectl apply -f examples/sample-task.yaml
```

### 6. Watch the Execution

```bash
kubectl get agentruns -w
kubectl logs -f deployment/adk-controller
```

## Local Development

```bash
# Create virtual environment
cd adk
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run controller locally (watches your cluster)
python -m controller.main
```

## Project Structure

```
adk/
├── controller/           # Kubernetes controller (Python/kopf)
│   ├── main.py          # Entry point
│   ├── handlers/        # CRD event handlers
│   └── services/        # Business logic
├── execution/           # Execution layer
│   ├── sandbox.py       # Sandbox execution (Docker-based)
│   ├── planner.py       # LLM planner interface
│   └── tools/           # Tool implementations
├── k8s/                 # Kubernetes manifests
│   ├── crds/           # Custom Resource Definitions
│   ├── controller/     # Controller deployment
│   └── vllm/           # vLLM deployment
├── examples/           # Example agents and tasks
└── tests/              # Test suite
```

## Components

### 1. CRDs (Custom Resource Definitions)
Define the schema for Agent, AgentTask, and AgentRun resources.

### 2. Controller
Watches for CRD events and orchestrates execution:
- Creates AgentRuns when AgentTasks are submitted
- Manages lifecycle (pending → running → completed/failed)
- Handles retries and failure recovery

### 3. Execution Layer
- **Planner**: Calls vLLM to decide next action
- **Sandbox**: Executes tools in isolated containers
- **Tools**: Implementations of available tools

### 4. Identity (Simplified)
For production, integrate SPIFFE/SPIRE. This demo uses simplified token-based auth.
