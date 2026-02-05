"""
Tests for the Tool Registry.
"""

import pytest
from controller.services.tools import ToolRegistry, ToolDefinition


class TestToolRegistry:
    """Test the tool registry."""
    
    def test_default_tools_registered(self):
        """Default tools should be registered on init."""
        registry = ToolRegistry()
        
        tools = registry.list_tools()
        
        assert "read_file" in tools
        assert "write_file" in tools
        assert "list_directory" in tools
        assert "shell" in tools
        assert "calculator" in tools
    
    def test_get_existing_tool(self):
        """Should return tool definition for existing tool."""
        registry = ToolRegistry()
        
        tool = registry.get_tool("read_file")
        
        assert tool is not None
        assert tool.name == "read_file"
        assert tool.execution_type == "python"
        assert "path" in tool.parameters.get("properties", {})
    
    def test_get_nonexistent_tool(self):
        """Should return None for nonexistent tool."""
        registry = ToolRegistry()
        
        tool = registry.get_tool("nonexistent_tool")
        
        assert tool is None
    
    def test_register_custom_tool(self):
        """Should allow registering custom tools."""
        registry = ToolRegistry()
        
        custom_tool = ToolDefinition(
            name="custom_tool",
            description="A custom tool",
            parameters={"type": "object", "properties": {}},
            execution_type="python",
            code="def execute(): return 'custom'",
        )
        
        registry.register(custom_tool)
        
        assert "custom_tool" in registry.list_tools()
        assert registry.get_tool("custom_tool") == custom_tool
    
    def test_get_tools_for_agent_all(self):
        """Empty allowed list should return all tools."""
        registry = ToolRegistry()
        
        tools = registry.get_tools_for_agent([])
        
        assert len(tools) == len(registry.list_tools())
    
    def test_get_tools_for_agent_filtered(self):
        """Should filter tools based on allowed list."""
        registry = ToolRegistry()
        
        tools = registry.get_tools_for_agent(["read_file", "write_file"])
        
        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "shell" not in tool_names


class TestToolExecution:
    """Test tool code execution."""
    
    def test_calculator_tool_code(self):
        """Calculator tool should work."""
        registry = ToolRegistry()
        tool = registry.get_tool("calculator")
        
        # Execute the tool code
        namespace = {}
        exec(tool.code, namespace)
        
        result = namespace["execute"]("2 + 2")
        assert result == 4
        
        result = namespace["execute"]("sqrt(16)")
        assert result == 4.0
    
    def test_python_eval_tool_code(self):
        """Python eval tool should work."""
        registry = ToolRegistry()
        tool = registry.get_tool("python_eval")
        
        namespace = {}
        exec(tool.code, namespace)
        
        result = namespace["execute"]("[x**2 for x in range(5)]")
        assert result == [0, 1, 4, 9, 16]
