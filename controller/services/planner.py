"""
Planner Service - LLM-based action planning.

The planner calls vLLM to decide the next action:
- "tool_call" with tool name and arguments
- "finish" with final answer
"""

import json
import structlog
from dataclasses import dataclass
from typing import Any, Optional
from openai import AsyncOpenAI

logger = structlog.get_logger(__name__)


@dataclass
class ToolInfo:
    """Information about an available tool."""
    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass
class PlannerResponse:
    """Response from the planner."""
    action: str  # "tool_call" or "finish"
    thought: str  # Reasoning
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    final_answer: Optional[str] = None
    tokens_used: int = 0


class Planner:
    """
    LLM-based planner that decides next actions.
    
    Uses vLLM with OpenAI-compatible API.
    """
    
    def __init__(self, vllm_endpoint: str, model: str):
        self.client = AsyncOpenAI(
            base_url=vllm_endpoint,
            api_key="not-needed",  # vLLM doesn't require API key
        )
        self.model = model
    
    async def plan(
        self,
        goal: str,
        system_prompt: str,
        history: list[dict],
        available_tools: list[ToolInfo],
        context: dict,
    ) -> PlannerResponse:
        """
        Plan the next action based on current state.
        
        Args:
            goal: The user's goal/instruction
            system_prompt: Agent's system prompt
            history: Conversation history
            available_tools: List of available tools
            context: Additional context
            
        Returns:
            PlannerResponse with next action
        """
        
        # Build the prompt
        tools_description = self._format_tools(available_tools)
        
        full_system_prompt = f"""{system_prompt}

## Available Tools

{tools_description}

## Response Format

You must respond with a JSON object in one of these formats:

For tool calls:
```json
{{
    "action": "tool_call",
    "thought": "Your reasoning for this action",
    "tool": "tool_name",
    "args": {{"arg1": "value1", "arg2": "value2"}}
}}
```

When the task is complete:
```json
{{
    "action": "finish",
    "thought": "Summary of what was accomplished",
    "answer": "Final answer or result"
}}
```

Always respond with valid JSON only, no other text.
"""
        
        # Build messages
        messages = [{"role": "system", "content": full_system_prompt}]
        
        # Add context if provided
        if context:
            messages.append({
                "role": "user",
                "content": f"Context:\n```json\n{json.dumps(context, indent=2)}\n```"
            })
        
        # Add goal
        messages.append({
            "role": "user",
            "content": f"Goal: {goal}"
        })
        
        # Add history
        for entry in history:
            if entry.get("role") == "assistant":
                content = entry.get("content", "")
                if entry.get("action") == "tool_call":
                    content = json.dumps({
                        "action": "tool_call",
                        "thought": entry.get("content"),
                        "tool": entry.get("tool"),
                        "args": entry.get("args"),
                    })
                messages.append({"role": "assistant", "content": content})
            elif entry.get("role") == "tool":
                tool_result = {
                    "tool": entry.get("tool"),
                    "success": entry.get("success"),
                }
                if entry.get("success"):
                    tool_result["output"] = entry.get("output", "")[:5000]
                else:
                    tool_result["error"] = entry.get("error", "Unknown error")
                messages.append({
                    "role": "user",
                    "content": f"Tool result:\n```json\n{json.dumps(tool_result, indent=2)}\n```"
                })
        
        # Call LLM
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
            )
            
            content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            logger.debug(f"LLM response: {content}")
            
            # Parse response
            return self._parse_response(content, tokens_used)
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def _format_tools(self, tools: list[ToolInfo]) -> str:
        """Format tools for the prompt."""
        if not tools:
            return "No tools available."
        
        lines = []
        for tool in tools:
            params_str = json.dumps(tool.parameters, indent=2)
            lines.append(f"""### {tool.name}
{tool.description}

Parameters:
```json
{params_str}
```
""")
        
        return "\n".join(lines)
    
    def _parse_response(self, content: str, tokens_used: int) -> PlannerResponse:
        """Parse LLM response into PlannerResponse."""
        
        # Try to extract JSON from response
        content = content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Content was: {content}")
            # Return a finish action with the raw content as answer
            return PlannerResponse(
                action="finish",
                thought="Failed to parse response, treating as final answer",
                final_answer=content,
                tokens_used=tokens_used,
            )
        
        action = data.get("action", "finish")
        thought = data.get("thought", "")
        
        if action == "tool_call":
            return PlannerResponse(
                action="tool_call",
                thought=thought,
                tool_name=data.get("tool"),
                tool_args=data.get("args", {}),
                tokens_used=tokens_used,
            )
        else:
            return PlannerResponse(
                action="finish",
                thought=thought,
                final_answer=data.get("answer", thought),
                tokens_used=tokens_used,
            )


class MockPlanner:
    """
    Mock planner for testing without LLM.
    
    Executes a predefined sequence of actions.
    """
    
    def __init__(self, actions: list[dict] = None):
        self.actions = actions or []
        self.call_count = 0
    
    async def plan(self, **kwargs) -> PlannerResponse:
        """Return next predefined action."""
        
        if self.call_count >= len(self.actions):
            return PlannerResponse(
                action="finish",
                thought="No more actions",
                final_answer="Completed all predefined actions",
                tokens_used=0,
            )
        
        action = self.actions[self.call_count]
        self.call_count += 1
        
        return PlannerResponse(
            action=action.get("action", "finish"),
            thought=action.get("thought", ""),
            tool_name=action.get("tool"),
            tool_args=action.get("args", {}),
            final_answer=action.get("answer"),
            tokens_used=0,
        )
