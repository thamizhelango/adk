"""
Tests for the Planner service.
"""

import pytest
from controller.services.planner import Planner, MockPlanner, PlannerResponse, ToolInfo


class TestMockPlanner:
    """Test the mock planner."""
    
    @pytest.mark.asyncio
    async def test_empty_actions_returns_finish(self):
        """Empty actions list should return finish."""
        planner = MockPlanner(actions=[])
        
        response = await planner.plan(
            goal="Test goal",
            system_prompt="Test prompt",
            history=[],
            available_tools=[],
            context={},
        )
        
        assert response.action == "finish"
    
    @pytest.mark.asyncio
    async def test_predefined_tool_call(self):
        """Should return predefined tool calls in order."""
        planner = MockPlanner(actions=[
            {
                "action": "tool_call",
                "thought": "Need to list files",
                "tool": "list_directory",
                "args": {"path": "/tmp"},
            },
            {
                "action": "finish",
                "thought": "Done",
                "answer": "Found files",
            },
        ])
        
        # First call
        response1 = await planner.plan(
            goal="List files",
            system_prompt="",
            history=[],
            available_tools=[],
            context={},
        )
        
        assert response1.action == "tool_call"
        assert response1.tool_name == "list_directory"
        assert response1.tool_args == {"path": "/tmp"}
        
        # Second call
        response2 = await planner.plan(
            goal="List files",
            system_prompt="",
            history=[],
            available_tools=[],
            context={},
        )
        
        assert response2.action == "finish"
        assert response2.final_answer == "Found files"


class TestPlannerResponseParsing:
    """Test response parsing logic."""
    
    def test_parse_tool_call(self):
        """Test parsing a tool call response."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        content = '''{"action": "tool_call", "thought": "Need to read", "tool": "read_file", "args": {"path": "/tmp/test.txt"}}'''
        
        response = planner._parse_response(content, 100)
        
        assert response.action == "tool_call"
        assert response.tool_name == "read_file"
        assert response.tool_args == {"path": "/tmp/test.txt"}
        assert response.tokens_used == 100
    
    def test_parse_finish(self):
        """Test parsing a finish response."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        content = '''{"action": "finish", "thought": "Done!", "answer": "The result is 42"}'''
        
        response = planner._parse_response(content, 50)
        
        assert response.action == "finish"
        assert response.final_answer == "The result is 42"
        assert response.tokens_used == 50
    
    def test_parse_with_markdown_wrapper(self):
        """Test parsing response wrapped in markdown code blocks."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        content = '''```json
{"action": "finish", "thought": "Done", "answer": "Success"}
```'''
        
        response = planner._parse_response(content, 0)
        
        assert response.action == "finish"
        assert response.final_answer == "Success"
    
    def test_parse_invalid_json_becomes_finish(self):
        """Invalid JSON should become a finish action with raw content."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        content = "This is not JSON, just a plain response"
        
        response = planner._parse_response(content, 0)
        
        assert response.action == "finish"
        assert "plain response" in response.final_answer


class TestToolFormatting:
    """Test tool formatting for prompts."""
    
    def test_format_single_tool(self):
        """Test formatting a single tool."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        tools = [
            ToolInfo(
                name="test_tool",
                description="A test tool",
                parameters={"type": "object", "properties": {"arg1": {"type": "string"}}},
            )
        ]
        
        formatted = planner._format_tools(tools)
        
        assert "test_tool" in formatted
        assert "A test tool" in formatted
        assert "arg1" in formatted
    
    def test_format_no_tools(self):
        """Test formatting empty tool list."""
        planner = Planner(vllm_endpoint="http://localhost:8000/v1", model="test")
        
        formatted = planner._format_tools([])
        
        assert "No tools available" in formatted
