#!/usr/bin/env python3
"""
Local Demo - Run an agent loop without Kubernetes.

This script demonstrates the agent execution loop locally,
useful for testing and development without a full cluster.
"""

import asyncio
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller.services.config import Config
from controller.services.planner import MockPlanner, Planner
from controller.services.sandbox import SandboxExecutor
from controller.services.tools import ToolRegistry


async def run_agent_loop(
    goal: str,
    system_prompt: str,
    max_steps: int = 5,
    use_mock_planner: bool = True,
    vllm_endpoint: str = None,
    model: str = None,
):
    """
    Run an agent loop locally.
    
    Args:
        goal: The task for the agent
        system_prompt: Agent's system prompt
        max_steps: Maximum execution steps
        use_mock_planner: Use mock planner (no LLM needed)
        vllm_endpoint: vLLM endpoint (if not using mock)
        model: Model name (if not using mock)
    """
    
    print("=" * 60)
    print("ADK Local Demo")
    print("=" * 60)
    print(f"Goal: {goal}")
    print(f"Max Steps: {max_steps}")
    print(f"Using Mock Planner: {use_mock_planner}")
    print("=" * 60)
    print()
    
    # Initialize services
    config = Config(use_docker_sandbox=False)  # Local execution
    tool_registry = ToolRegistry()
    sandbox = SandboxExecutor(config)
    
    # Get available tools
    available_tools = tool_registry.get_tools_for_agent([])
    print(f"Available tools: {[t.name for t in available_tools]}")
    print()
    
    # Initialize planner
    if use_mock_planner:
        # Mock planner with predefined actions for demo
        planner = MockPlanner(actions=[
            {
                "action": "tool_call",
                "thought": "First, I'll list the current directory to see what files are here.",
                "tool": "list_directory",
                "args": {"path": "."},
            },
            {
                "action": "tool_call",
                "thought": "Let me do a quick calculation as a demo.",
                "tool": "calculator",
                "args": {"expression": "2 ** 10"},
            },
            {
                "action": "finish",
                "thought": "I've completed the demo tasks.",
                "answer": "Demo completed! I listed the directory and calculated 2^10 = 1024.",
            },
        ])
    else:
        if not vllm_endpoint or not model:
            print("ERROR: vllm_endpoint and model required when not using mock")
            return
        planner = Planner(vllm_endpoint=vllm_endpoint, model=model)
    
    # Run the agent loop
    history = []
    
    for step in range(1, max_steps + 1):
        print(f"--- Step {step}/{max_steps} ---")
        
        # Get next action from planner
        response = await planner.plan(
            goal=goal,
            system_prompt=system_prompt,
            history=history,
            available_tools=available_tools,
            context={},
        )
        
        print(f"Thought: {response.thought}")
        print(f"Action: {response.action}")
        
        if response.action == "finish":
            print(f"Final Answer: {response.final_answer}")
            print()
            print("=" * 60)
            print("Agent completed successfully!")
            print("=" * 60)
            return
        
        if response.action == "tool_call":
            print(f"Tool: {response.tool_name}")
            print(f"Args: {json.dumps(response.tool_args, indent=2)}")
            
            # Execute tool
            result = await sandbox.execute_tool(
                tool_name=response.tool_name,
                tool_args=response.tool_args,
            )
            
            print(f"Success: {result.success}")
            if result.success:
                output = result.output
                if output and len(output) > 500:
                    output = output[:500] + "...(truncated)"
                print(f"Output: {output}")
            else:
                print(f"Error: {result.error}")
            
            # Add to history
            history.append({
                "role": "assistant",
                "content": response.thought,
                "action": response.action,
                "tool": response.tool_name,
                "args": response.tool_args,
            })
            history.append({
                "role": "tool",
                "tool": response.tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
            })
        
        print()
    
    print("=" * 60)
    print("Reached maximum steps!")
    print("=" * 60)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run ADK agent locally")
    parser.add_argument(
        "--goal",
        default="List the files in the current directory and tell me what you find.",
        help="Goal for the agent",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=5,
        help="Maximum steps",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use real LLM instead of mock",
    )
    parser.add_argument(
        "--vllm-endpoint",
        default="http://localhost:8000/v1",
        help="vLLM endpoint URL",
    )
    parser.add_argument(
        "--model",
        default="codellama/CodeLlama-7b-Instruct-hf",
        help="Model name",
    )
    
    args = parser.parse_args()
    
    system_prompt = """You are a helpful AI assistant.
You can use tools to accomplish tasks.
Think step by step and explain your reasoning."""
    
    asyncio.run(run_agent_loop(
        goal=args.goal,
        system_prompt=system_prompt,
        max_steps=args.max_steps,
        use_mock_planner=not args.use_llm,
        vllm_endpoint=args.vllm_endpoint,
        model=args.model,
    ))


if __name__ == "__main__":
    main()
