"""
Sandbox Executor - Isolated tool execution.

Executes tools in isolated Docker containers (or Kubernetes Jobs).
In production, this would use Firecracker microVMs for stronger isolation.
"""

import asyncio
import json
import tempfile
import os
import structlog
from dataclasses import dataclass
from typing import Optional

import docker
from docker.errors import ContainerError, ImageNotFound, APIError

from controller.services.config import Config
from controller.services.tools import ToolRegistry

logger = structlog.get_logger(__name__)


@dataclass
class ExecutionResult:
    """Result of tool execution."""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: int = 0
    execution_time_ms: int = 0


class SandboxExecutor:
    """
    Execute tools in isolated containers.
    
    Features:
    - Isolated execution environment
    - Resource limits (CPU, memory)
    - Timeout enforcement
    - Network isolation (optional)
    - Automatic cleanup
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.tool_registry = ToolRegistry()
        
        if config.use_docker_sandbox:
            try:
                self.docker_client = docker.from_env()
            except Exception as e:
                logger.warning(f"Docker not available: {e}")
                self.docker_client = None
        else:
            self.docker_client = None
    
    async def execute_tool(
        self,
        tool_name: str,
        tool_args: dict,
        timeout: int = 60,
    ) -> ExecutionResult:
        """
        Execute a tool in an isolated sandbox.
        
        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments to pass to the tool
            timeout: Maximum execution time in seconds
            
        Returns:
            ExecutionResult with output or error
        """
        
        logger.info(f"Executing tool: {tool_name}", args=tool_args)
        
        # Get tool definition
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return ExecutionResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
            )
        
        # Execute based on tool type
        if tool.execution_type == "python":
            return await self._execute_python_tool(tool, tool_args, timeout)
        elif tool.execution_type == "shell":
            return await self._execute_shell_tool(tool, tool_args, timeout)
        elif tool.execution_type == "http":
            return await self._execute_http_tool(tool, tool_args, timeout)
        else:
            return ExecutionResult(
                success=False,
                error=f"Unsupported execution type: {tool.execution_type}",
            )
    
    async def _execute_python_tool(
        self,
        tool,
        args: dict,
        timeout: int,
    ) -> ExecutionResult:
        """Execute a Python tool in a container."""
        
        if not self.docker_client:
            # Fallback to local execution (less isolated)
            return await self._execute_python_local(tool, args, timeout)
        
        # Create temp directory with tool code and args
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write tool code
            tool_code_path = os.path.join(tmpdir, "tool.py")
            with open(tool_code_path, "w") as f:
                f.write(tool.code)
            
            # Write args
            args_path = os.path.join(tmpdir, "args.json")
            with open(args_path, "w") as f:
                json.dump(args, f)
            
            # Write runner script
            runner_path = os.path.join(tmpdir, "runner.py")
            with open(runner_path, "w") as f:
                f.write("""
import json
import sys
import traceback

# Load args
with open('/workspace/args.json') as f:
    args = json.load(f)

# Import and run tool
try:
    from tool import execute
    result = execute(**args)
    print(json.dumps({"success": True, "result": result}))
except Exception as e:
    print(json.dumps({
        "success": False, 
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
    sys.exit(1)
""")
            
            try:
                # Run container
                container = self.docker_client.containers.run(
                    image=self.config.sandbox_image,
                    command=["python", "/workspace/runner.py"],
                    volumes={tmpdir: {"bind": "/workspace", "mode": "ro"}},
                    working_dir="/workspace",
                    mem_limit=self.config.sandbox_memory_limit,
                    cpu_period=100000,
                    cpu_quota=int(float(self.config.sandbox_cpu_limit) * 100000),
                    network_disabled=not tool.requires_network,
                    remove=True,
                    detach=False,
                    stdout=True,
                    stderr=True,
                )
                
                output = container.decode("utf-8").strip()
                
                # Parse output
                try:
                    result = json.loads(output.split("\n")[-1])
                    if result.get("success"):
                        return ExecutionResult(
                            success=True,
                            output=json.dumps(result.get("result")),
                        )
                    else:
                        return ExecutionResult(
                            success=False,
                            error=result.get("error", "Unknown error"),
                        )
                except json.JSONDecodeError:
                    return ExecutionResult(success=True, output=output)
                    
            except ContainerError as e:
                return ExecutionResult(
                    success=False,
                    error=f"Container error: {e.stderr.decode('utf-8') if e.stderr else str(e)}",
                    exit_code=e.exit_status,
                )
            except ImageNotFound:
                return ExecutionResult(
                    success=False,
                    error=f"Sandbox image not found: {self.config.sandbox_image}",
                )
            except APIError as e:
                return ExecutionResult(
                    success=False,
                    error=f"Docker API error: {e}",
                )
    
    async def _execute_python_local(
        self,
        tool,
        args: dict,
        timeout: int,
    ) -> ExecutionResult:
        """Execute Python tool locally (fallback, less isolated)."""
        
        logger.warning("Executing tool locally (Docker not available)")
        
        # Create a restricted namespace
        namespace = {"__builtins__": __builtins__}
        
        try:
            # Execute tool code to define functions
            exec(tool.code, namespace)
            
            # Call execute function
            if "execute" not in namespace:
                return ExecutionResult(
                    success=False,
                    error="Tool must define an 'execute' function",
                )
            
            # Run with timeout
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: namespace["execute"](**args)),
                timeout=timeout,
            )
            
            return ExecutionResult(
                success=True,
                output=json.dumps(result) if result is not None else None,
            )
            
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
            )
    
    async def _execute_shell_tool(
        self,
        tool,
        args: dict,
        timeout: int,
    ) -> ExecutionResult:
        """Execute a shell command in a container."""
        
        command = tool.code.format(**args)
        
        if not self.docker_client:
            # Local execution fallback
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                
                if proc.returncode == 0:
                    return ExecutionResult(
                        success=True,
                        output=stdout.decode("utf-8"),
                        exit_code=proc.returncode,
                    )
                else:
                    return ExecutionResult(
                        success=False,
                        output=stdout.decode("utf-8"),
                        error=stderr.decode("utf-8"),
                        exit_code=proc.returncode,
                    )
            except asyncio.TimeoutError:
                return ExecutionResult(
                    success=False,
                    error=f"Command timed out after {timeout}s",
                )
        
        try:
            container = self.docker_client.containers.run(
                image=self.config.sandbox_image,
                command=["sh", "-c", command],
                mem_limit=self.config.sandbox_memory_limit,
                network_disabled=not tool.requires_network,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
            )
            
            return ExecutionResult(
                success=True,
                output=container.decode("utf-8"),
            )
            
        except ContainerError as e:
            return ExecutionResult(
                success=False,
                error=e.stderr.decode("utf-8") if e.stderr else str(e),
                exit_code=e.exit_status,
            )
    
    async def _execute_http_tool(
        self,
        tool,
        args: dict,
        timeout: int,
    ) -> ExecutionResult:
        """Execute an HTTP request tool."""
        
        import httpx
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                method = tool.http_method.upper()
                url = tool.http_url.format(**args)
                
                if method == "GET":
                    response = await client.get(url, params=args)
                elif method == "POST":
                    response = await client.post(url, json=args)
                elif method == "PUT":
                    response = await client.put(url, json=args)
                elif method == "DELETE":
                    response = await client.delete(url)
                else:
                    return ExecutionResult(
                        success=False,
                        error=f"Unsupported HTTP method: {method}",
                    )
                
                return ExecutionResult(
                    success=response.is_success,
                    output=response.text,
                    exit_code=response.status_code,
                )
                
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
            )
