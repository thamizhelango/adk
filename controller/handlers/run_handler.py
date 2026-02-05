"""
AgentRun CRD Handler

Handles lifecycle events for AgentRun resources.
Runs are the actual execution instances where the agent loop runs.

This is the core of the agent execution:
1. Call LLM (planner) to decide next action
2. Execute tool in sandbox
3. Feed result back to LLM
4. Repeat until done or max steps reached
"""

import asyncio
import kopf
import structlog
from datetime import datetime, timezone
from kubernetes import client

from controller.services.config import Config
from controller.services.planner import Planner, PlannerResponse
from controller.services.sandbox import SandboxExecutor
from controller.services.tools import ToolRegistry

logger = structlog.get_logger(__name__)

API_GROUP = "ai.adk.io"
API_VERSION = "v1"


def get_custom_api():
    """Get Kubernetes custom objects API client."""
    return client.CustomObjectsApi()


def update_run_status(namespace: str, name: str, status_patch: dict):
    """Helper to update AgentRun status."""
    api = get_custom_api()
    api.patch_namespaced_custom_object_status(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="agentruns",
        name=name,
        body={"status": status_patch},
    )


def append_history(namespace: str, name: str, entry: dict):
    """Append an entry to the run history."""
    api = get_custom_api()
    
    # Get current run
    run = api.get_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="agentruns",
        name=name,
    )
    
    history = run.get("status", {}).get("history", [])
    history.append({
        **entry,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    
    api.patch_namespaced_custom_object_status(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="agentruns",
        name=name,
        body={"status": {"history": history}},
    )


@kopf.on.create(API_GROUP, API_VERSION, "agentruns")
async def run_created(spec, name, namespace, logger, **kwargs):
    """
    Handle AgentRun creation - this is where the magic happens.
    
    Executes the agent loop:
    1. Initialize execution context
    2. Loop until done or max steps:
       a. Call planner (LLM) with current state
       b. If planner says done, finish
       c. If planner says tool call, execute in sandbox
       d. Record result, increment step
    3. Update final status
    """
    
    logger.info(f"AgentRun created: {name}")
    
    agent_ref = spec.get("agentRef")
    goal = spec.get("goal")
    context = spec.get("context", {})
    max_steps = spec.get("maxSteps", 10)
    timeout = spec.get("timeout", 300)
    
    # Initialize status
    update_run_status(namespace, name, {
        "phase": "Planning",
        "currentStep": 0,
        "history": [],
        "startTime": datetime.now(timezone.utc).isoformat(),
        "resourcesUsed": {
            "llmTokens": 0,
            "toolExecutions": 0,
            "wallTimeSeconds": 0,
        },
    })
    
    # Get the agent configuration
    api = get_custom_api()
    try:
        agent = api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="agents",
            name=agent_ref,
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            update_run_status(namespace, name, {
                "phase": "Failed",
                "error": f"Agent '{agent_ref}' not found",
            })
            raise kopf.PermanentError(f"Agent '{agent_ref}' not found")
        raise
    
    agent_spec = agent.get("spec", {})
    
    # Initialize services
    config = Config.from_env()
    planner = Planner(
        vllm_endpoint=config.vllm_endpoint,
        model=agent_spec.get("model"),
    )
    tool_registry = ToolRegistry()
    sandbox = SandboxExecutor(config=config)
    
    # Get available tools for this agent
    allowed_tools = agent_spec.get("tools", [])
    available_tools = tool_registry.get_tools_for_agent(allowed_tools)
    
    # Build system prompt
    system_prompt = agent_spec.get("systemPrompt", "You are a helpful AI agent.")
    
    # Execution state
    history = []
    current_step = 0
    total_tokens = 0
    tool_executions = 0
    start_time = datetime.now(timezone.utc)
    
    try:
        # Main agent loop
        while current_step < max_steps:
            current_step += 1
            
            logger.info(f"Run {name} step {current_step}/{max_steps}")
            update_run_status(namespace, name, {
                "phase": "Planning",
                "currentStep": current_step,
            })
            
            # Check timeout
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"Run exceeded timeout of {timeout}s")
            
            # Call planner
            try:
                planner_response = await planner.plan(
                    goal=goal,
                    system_prompt=system_prompt,
                    history=history,
                    available_tools=available_tools,
                    context=context,
                )
                total_tokens += planner_response.tokens_used
            except Exception as e:
                logger.error(f"Planner error: {e}")
                append_history(namespace, name, {
                    "step": current_step,
                    "type": "error",
                    "data": {"error": str(e), "source": "planner"},
                })
                raise
            
            # Record the plan
            append_history(namespace, name, {
                "step": current_step,
                "type": "plan",
                "data": {
                    "action": planner_response.action,
                    "thought": planner_response.thought,
                    "tool": planner_response.tool_name,
                    "args": planner_response.tool_args,
                },
            })
            
            history.append({
                "role": "assistant",
                "content": planner_response.thought,
                "action": planner_response.action,
                "tool": planner_response.tool_name,
                "args": planner_response.tool_args,
            })
            
            # Check if done
            if planner_response.action == "finish":
                logger.info(f"Run {name} completed successfully")
                update_run_status(namespace, name, {
                    "phase": "Completed",
                    "result": {
                        "success": True,
                        "output": planner_response.final_answer,
                        "steps_taken": current_step,
                    },
                    "completionTime": datetime.now(timezone.utc).isoformat(),
                    "resourcesUsed": {
                        "llmTokens": total_tokens,
                        "toolExecutions": tool_executions,
                        "wallTimeSeconds": elapsed,
                    },
                })
                
                # Update agent stats
                _update_agent_stats(namespace, agent_ref, success=True)
                
                return {"phase": "Completed"}
            
            # Execute tool
            if planner_response.action == "tool_call":
                tool_name = planner_response.tool_name
                tool_args = planner_response.tool_args
                
                logger.info(f"Executing tool: {tool_name}")
                update_run_status(namespace, name, {"phase": "Executing"})
                
                try:
                    tool_executions += 1
                    result = await sandbox.execute_tool(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        timeout=min(60, timeout - elapsed),  # Remaining time
                    )
                    
                    append_history(namespace, name, {
                        "step": current_step,
                        "type": "tool_result",
                        "data": {
                            "tool": tool_name,
                            "success": result.success,
                            "output": result.output[:5000] if result.output else None,
                            "error": result.error,
                        },
                    })
                    
                    history.append({
                        "role": "tool",
                        "tool": tool_name,
                        "success": result.success,
                        "output": result.output,
                        "error": result.error,
                    })
                    
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")
                    append_history(namespace, name, {
                        "step": current_step,
                        "type": "error",
                        "data": {"error": str(e), "source": "sandbox"},
                    })
                    history.append({
                        "role": "tool",
                        "tool": tool_name,
                        "success": False,
                        "error": str(e),
                    })
        
        # Max steps reached
        logger.warning(f"Run {name} reached max steps ({max_steps})")
        update_run_status(namespace, name, {
            "phase": "Failed",
            "error": f"Reached maximum steps ({max_steps}) without completing",
            "completionTime": datetime.now(timezone.utc).isoformat(),
            "resourcesUsed": {
                "llmTokens": total_tokens,
                "toolExecutions": tool_executions,
                "wallTimeSeconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            },
        })
        _update_agent_stats(namespace, agent_ref, success=False)
        
        return {"phase": "Failed"}
        
    except Exception as e:
        logger.error(f"Run {name} failed: {e}")
        update_run_status(namespace, name, {
            "phase": "Failed",
            "error": str(e),
            "completionTime": datetime.now(timezone.utc).isoformat(),
            "resourcesUsed": {
                "llmTokens": total_tokens,
                "toolExecutions": tool_executions,
                "wallTimeSeconds": (datetime.now(timezone.utc) - start_time).total_seconds(),
            },
        })
        _update_agent_stats(namespace, agent_ref, success=False)
        
        raise kopf.PermanentError(str(e))


def _update_agent_stats(namespace: str, agent_name: str, success: bool):
    """Update agent run statistics."""
    api = get_custom_api()
    
    try:
        agent = api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="agents",
            name=agent_name,
        )
        
        status = agent.get("status", {})
        total_runs = status.get("totalRuns", 0) + 1
        successful_runs = status.get("successfulRuns", 0) + (1 if success else 0)
        failed_runs = status.get("failedRuns", 0) + (0 if success else 1)
        
        api.patch_namespaced_custom_object_status(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="agents",
            name=agent_name,
            body={
                "status": {
                    "totalRuns": total_runs,
                    "successfulRuns": successful_runs,
                    "failedRuns": failed_runs,
                    "lastRunTime": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    except Exception as e:
        logger.warning(f"Failed to update agent stats: {e}")
