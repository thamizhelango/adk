# ADK Makefile
.PHONY: help install test demo crds controller clean

# Default target
help:
	@echo "ADK - Agent Development Kit"
	@echo ""
	@echo "Available targets:"
	@echo "  install     - Install Python dependencies"
	@echo "  test        - Run unit tests"
	@echo "  demo        - Run local demo (no Kubernetes needed)"
	@echo "  demo-llm    - Run demo with real LLM (requires vLLM)"
	@echo "  crds        - Install CRDs to Kubernetes"
	@echo "  controller  - Deploy controller to Kubernetes"
	@echo "  vllm-mock   - Deploy mock vLLM service"
	@echo "  spire       - Deploy SPIRE (SPIFFE) for identity"
	@echo "  agent       - Create example SRE agent"
	@echo "  task        - Submit example task"
	@echo "  logs        - View controller logs"
	@echo "  clean       - Clean up resources"
	@echo ""

# Install dependencies
install:
	python3 -m venv venv || true
	. venv/bin/activate && pip install -r requirements.txt

# Run tests
test:
	. venv/bin/activate && pytest

# Run local demo (no K8s needed)
demo:
	. venv/bin/activate && python scripts/demo-local.py

# Run demo with real LLM
demo-llm:
	. venv/bin/activate && python scripts/demo-local.py --use-llm

# Install CRDs
crds:
	kubectl apply -f k8s/crds/

# Deploy controller
controller: crds
	kubectl apply -f k8s/controller/namespace.yaml
	kubectl apply -f k8s/controller/rbac.yaml
	kubectl apply -f k8s/controller/deployment.yaml

# Deploy mock vLLM
vllm-mock:
	kubectl apply -f k8s/vllm-mock/

# Create example agent
agent:
	kubectl apply -f examples/sre-agent.yaml

# Submit example task
task:
	kubectl apply -f examples/sample-task.yaml

# View controller logs
logs:
	kubectl logs -f deployment/adk-controller -n adk-system

# Watch agent runs
watch:
	kubectl get agentruns -w

# Deploy SPIRE (SPIFFE implementation)
spire:
	kubectl apply -f k8s/spire/spire-server.yaml
	@echo "Waiting for SPIRE Server..."
	kubectl wait --for=condition=ready pod -l app=spire-server -n spire --timeout=120s
	kubectl apply -f k8s/spire/spire-agent.yaml
	@echo "Waiting for SPIRE Agent..."
	sleep 10
	kubectl apply -f k8s/spire/workload-registration.yaml

# Clean up
clean:
	kubectl delete -f examples/ --ignore-not-found || true
	kubectl delete -f k8s/controller/ --ignore-not-found || true
	kubectl delete -f k8s/vllm-mock/ --ignore-not-found || true
	kubectl delete -f k8s/spire/ --ignore-not-found || true
	kubectl delete -f k8s/crds/ --ignore-not-found || true
