"""
Tool Registry - Definition and management of available tools.

Tools are the actions that agents can take.
Each tool has:
- Name and description (for LLM)
- Parameter schema (for validation)
- Execution code (Python, shell, or HTTP)
"""

import json
from dataclasses import dataclass, field
from typing import Optional
from controller.services.planner import ToolInfo


@dataclass
class ToolDefinition:
    """Complete tool definition."""
    
    name: str
    description: str
    parameters: dict  # JSON Schema
    execution_type: str  # "python", "shell", "http"
    code: str  # Python code, shell command template, or HTTP config
    requires_network: bool = False
    http_method: str = "GET"
    http_url: str = ""
    allowed_agents: list = field(default_factory=list)  # Empty = all agents


class ToolRegistry:
    """
    Registry of available tools.
    
    In production, tools might be loaded from:
    - Kubernetes ConfigMaps
    - A database
    - Tool CRDs
    """
    
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register built-in tools."""
        
        # Read file tool
        self.register(ToolDefinition(
            name="read_file",
            description="Read the contents of a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read"
                    }
                },
                "required": ["path"]
            },
            execution_type="python",
            code='''
def execute(path: str) -> str:
    """Read file contents."""
    with open(path, 'r') as f:
        return f.read()
''',
        ))
        
        # Write file tool
        self.register(ToolDefinition(
            name="write_file",
            description="Write content to a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    }
                },
                "required": ["path", "content"]
            },
            execution_type="python",
            code='''
def execute(path: str, content: str) -> str:
    """Write content to file."""
    with open(path, 'w') as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"
''',
        ))
        
        # List directory tool
        self.register(ToolDefinition(
            name="list_directory",
            description="List files and directories in a path",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                        "default": "."
                    }
                },
                "required": []
            },
            execution_type="python",
            code='''
import os

def execute(path: str = ".") -> list:
    """List directory contents."""
    entries = []
    for entry in os.listdir(path):
        full_path = os.path.join(path, entry)
        entries.append({
            "name": entry,
            "type": "directory" if os.path.isdir(full_path) else "file",
            "size": os.path.getsize(full_path) if os.path.isfile(full_path) else None,
        })
    return entries
''',
        ))
        
        # Shell command tool
        self.register(ToolDefinition(
            name="shell",
            description="Execute a shell command. Use with caution.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    }
                },
                "required": ["command"]
            },
            execution_type="shell",
            code="{command}",
        ))
        
        # Python eval tool
        self.register(ToolDefinition(
            name="python_eval",
            description="Evaluate a Python expression and return the result",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Python expression to evaluate"
                    }
                },
                "required": ["expression"]
            },
            execution_type="python",
            code='''
def execute(expression: str):
    """Evaluate Python expression."""
    return eval(expression)
''',
        ))
        
        # HTTP GET tool
        self.register(ToolDefinition(
            name="http_get",
            description="Make an HTTP GET request",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to request"
                    }
                },
                "required": ["url"]
            },
            execution_type="python",
            requires_network=True,
            code='''
import urllib.request
import json

def execute(url: str) -> str:
    """Make HTTP GET request."""
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode('utf-8')
''',
        ))
        
        # Search/grep tool
        self.register(ToolDefinition(
            name="search_files",
            description="Search for a pattern in files",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in",
                        "default": "."
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "File pattern to match (e.g., '*.py')",
                        "default": "*"
                    }
                },
                "required": ["pattern"]
            },
            execution_type="python",
            code='''
import os
import re
import fnmatch

def execute(pattern: str, path: str = ".", file_pattern: str = "*") -> list:
    """Search for pattern in files."""
    results = []
    regex = re.compile(pattern)
    
    for root, dirs, files in os.walk(path):
        for filename in files:
            if fnmatch.fnmatch(filename, file_pattern):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, 'r') as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append({
                                    "file": filepath,
                                    "line": i,
                                    "content": line.strip()
                                })
                except (IOError, UnicodeDecodeError):
                    pass
    
    return results[:100]  # Limit results
''',
        ))
        
        # Calculator tool
        self.register(ToolDefinition(
            name="calculator",
            description="Perform mathematical calculations",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression (e.g., '2 + 2 * 3')"
                    }
                },
                "required": ["expression"]
            },
            execution_type="python",
            code='''
import math

def execute(expression: str) -> float:
    """Evaluate mathematical expression."""
    # Safe eval with math functions only
    allowed = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "sqrt": math.sqrt,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "exp": math.exp,
        "pi": math.pi, "e": math.e,
    }
    return eval(expression, {"__builtins__": {}}, allowed)
''',
        ))
    
    def register(self, tool: ToolDefinition):
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())
    
    def get_tools_for_agent(self, allowed_tools: list[str]) -> list[ToolInfo]:
        """
        Get tools available for an agent.
        
        Args:
            allowed_tools: List of tool names the agent can use.
                          Empty list means all tools.
        
        Returns:
            List of ToolInfo for the planner.
        """
        result = []
        
        for name, tool in self._tools.items():
            # Check if tool is allowed
            if allowed_tools and name not in allowed_tools:
                continue
            
            result.append(ToolInfo(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            ))
        
        return result
