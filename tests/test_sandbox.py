"""
Tests for the Sandbox Executor.
"""

import pytest
from controller.services.sandbox import SandboxExecutor, ExecutionResult
from controller.services.config import Config
from controller.services.tools import ToolRegistry


class TestSandboxExecutor:
    """Test the sandbox executor."""
    
    @pytest.fixture
    def executor(self):
        """Create executor with local execution (no Docker)."""
        config = Config(use_docker_sandbox=False)
        return SandboxExecutor(config)
    
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, executor):
        """Should return error for unknown tool."""
        result = await executor.execute_tool(
            tool_name="nonexistent_tool",
            tool_args={},
        )
        
        assert not result.success
        assert "Unknown tool" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_calculator(self, executor):
        """Should execute calculator tool."""
        result = await executor.execute_tool(
            tool_name="calculator",
            tool_args={"expression": "2 + 3 * 4"},
        )
        
        assert result.success
        assert "14" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_python_eval(self, executor):
        """Should execute python_eval tool."""
        result = await executor.execute_tool(
            tool_name="python_eval",
            tool_args={"expression": "len('hello')"},
        )
        
        assert result.success
        assert "5" in result.output
    
    @pytest.mark.asyncio
    async def test_execute_list_directory(self, executor):
        """Should execute list_directory tool."""
        result = await executor.execute_tool(
            tool_name="list_directory",
            tool_args={"path": "."},
        )
        
        assert result.success
        assert result.output is not None


class TestExecutionResult:
    """Test ExecutionResult dataclass."""
    
    def test_success_result(self):
        """Test successful result."""
        result = ExecutionResult(
            success=True,
            output="Hello, World!",
        )
        
        assert result.success
        assert result.output == "Hello, World!"
        assert result.error is None
    
    def test_failure_result(self):
        """Test failed result."""
        result = ExecutionResult(
            success=False,
            error="Something went wrong",
            exit_code=1,
        )
        
        assert not result.success
        assert result.error == "Something went wrong"
        assert result.exit_code == 1
