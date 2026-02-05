"""
Agent CRD Handler

Handles lifecycle events for Agent resources.
Agents are the logical entities that define behavior.
"""

import kopf
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger(__name__)

# API group and version for our CRDs
API_GROUP = "ai.adk.io"
API_VERSION = "v1"


@kopf.on.create(API_GROUP, API_VERSION, "agents")
async def agent_created(spec, name, namespace, logger, **kwargs):
    """Handle Agent creation."""
    
    logger.info(f"Agent created: {name}")
    
    # Validate the agent spec
    model = spec.get("model")
    system_prompt = spec.get("systemPrompt")
    tools = spec.get("tools", [])
    
    if not model:
        raise kopf.PermanentError("Agent must have a model specified")
    
    if not system_prompt:
        raise kopf.PermanentError("Agent must have a systemPrompt specified")
    
    logger.info(f"Agent {name} configured with model={model}, tools={tools}")
    
    # Return status patch
    return {
        "phase": "Active",
        "totalRuns": 0,
        "successfulRuns": 0,
        "failedRuns": 0,
    }


@kopf.on.update(API_GROUP, API_VERSION, "agents")
async def agent_updated(spec, name, namespace, status, logger, **kwargs):
    """Handle Agent updates."""
    
    logger.info(f"Agent updated: {name}")
    
    # Validate updated spec
    model = spec.get("model")
    if not model:
        raise kopf.PermanentError("Agent must have a model specified")
    
    # Keep existing status but mark as active
    return {"phase": "Active"}


@kopf.on.delete(API_GROUP, API_VERSION, "agents")
async def agent_deleted(name, namespace, logger, **kwargs):
    """Handle Agent deletion."""
    
    logger.info(f"Agent deleted: {name}")
    
    # Note: In production, you might want to:
    # - Cancel any running tasks for this agent
    # - Clean up associated resources
    # For now, Kubernetes garbage collection handles orphaned resources


@kopf.on.field(API_GROUP, API_VERSION, "agents", field="status.totalRuns")
async def agent_run_count_changed(old, new, name, namespace, logger, **kwargs):
    """React to run count changes (for metrics/logging)."""
    
    if old is not None and new is not None:
        logger.info(f"Agent {name} run count: {old} -> {new}")
