"""
Configuration management for ADK Controller.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Controller configuration."""
    
    # vLLM endpoint
    vllm_endpoint: str = "http://vllm-service:8000/v1"
    
    # Kubernetes namespace to watch (None = all namespaces)
    namespace: Optional[str] = None
    
    # Sandbox configuration
    sandbox_image: str = "python:3.11-slim"
    sandbox_cpu_limit: str = "1"
    sandbox_memory_limit: str = "512Mi"
    sandbox_timeout: int = 60
    
    # Use Docker for sandbox (alternative: Kubernetes Jobs)
    use_docker_sandbox: bool = True
    
    # SPIFFE socket path (for production identity)
    spiffe_socket: Optional[str] = None
    
    # Default model if not specified in agent
    default_model: str = "codellama/CodeLlama-7b-Instruct-hf"
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            vllm_endpoint=os.getenv("VLLM_ENDPOINT", "http://vllm-service:8000/v1"),
            namespace=os.getenv("WATCH_NAMESPACE", None),
            sandbox_image=os.getenv("SANDBOX_IMAGE", "python:3.11-slim"),
            sandbox_cpu_limit=os.getenv("SANDBOX_CPU_LIMIT", "1"),
            sandbox_memory_limit=os.getenv("SANDBOX_MEMORY_LIMIT", "512Mi"),
            sandbox_timeout=int(os.getenv("SANDBOX_TIMEOUT", "60")),
            use_docker_sandbox=os.getenv("USE_DOCKER_SANDBOX", "true").lower() == "true",
            spiffe_socket=os.getenv("SPIFFE_SOCKET"),
            default_model=os.getenv("DEFAULT_MODEL", "codellama/CodeLlama-7b-Instruct-hf"),
        )
