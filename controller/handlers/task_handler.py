"""
AgentTask CRD Handler

Handles lifecycle events for AgentTask resources.
Tasks are user requests that get executed by agents.
"""

import kopf
import structlog
from datetime import datetime, timezone
from kubernetes import client
from controller.services.config import Config

logger = structlog.get_logger(__name__)

API_GROUP = "ai.adk.io"
API_VERSION = "v1"


def get_custom_api():
    """Get Kubernetes custom objects API client."""
    return client.CustomObjectsApi()


@kopf.on.create(API_GROUP, API_VERSION, "agenttasks")
async def task_created(spec, name, namespace, logger, **kwargs):
    """
    Handle AgentTask creation.
    
    When a task is created:
    1. Validate the referenced agent exists
    2. Create an AgentRun to execute the task
    3. Update task status to Running
    """
    
    logger.info(f"AgentTask created: {name}")
    
    agent_ref = spec.get("agentRef")
    goal = spec.get("goal")
    context = spec.get("context", {})
    
    if not agent_ref:
        raise kopf.PermanentError("AgentTask must reference an agent")
    
    if not goal:
        raise kopf.PermanentError("AgentTask must have a goal")
    
    # Get the custom API client
    api = get_custom_api()
    
    # Verify the agent exists
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
            raise kopf.PermanentError(f"Agent '{agent_ref}' not found")
        raise
    
    agent_spec = agent.get("spec", {})
    
    # Create an AgentRun
    run_name = f"{name}-run-1"
    run_body = {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "AgentRun",
        "metadata": {
            "name": run_name,
            "namespace": namespace,
            "labels": {
                "ai.adk.io/agent": agent_ref,
                "ai.adk.io/task": name,
            },
            "ownerReferences": [{
                "apiVersion": f"{API_GROUP}/{API_VERSION}",
                "kind": "AgentTask",
                "name": name,
                "uid": kwargs.get("uid"),
                "controller": True,
                "blockOwnerDeletion": True,
            }],
        },
        "spec": {
            "agentRef": agent_ref,
            "taskRef": name,
            "goal": goal,
            "context": context,
            "maxSteps": agent_spec.get("maxSteps", 10),
            "timeout": agent_spec.get("timeout", 300),
        },
    }
    
    try:
        api.create_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="agentruns",
            body=run_body,
        )
        logger.info(f"Created AgentRun: {run_name}")
    except client.exceptions.ApiException as e:
        logger.error(f"Failed to create AgentRun: {e}")
        raise kopf.TemporaryError(f"Failed to create run: {e}", delay=10)
    
    return {
        "phase": "Running",
        "currentRun": run_name,
        "retryCount": 0,
        "startTime": datetime.now(timezone.utc).isoformat(),
    }


@kopf.on.field(API_GROUP, API_VERSION, "agentruns", field="status.phase")
async def run_phase_changed(old, new, name, namespace, spec, logger, **kwargs):
    """
    Watch AgentRun status changes and update parent AgentTask.
    
    When a run completes or fails, update the task accordingly.
    """
    
    if new not in ("Completed", "Failed"):
        return
    
    task_ref = spec.get("taskRef")
    if not task_ref:
        return
    
    logger.info(f"AgentRun {name} phase changed: {old} -> {new}")
    
    api = get_custom_api()
    
    try:
        task = api.get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="agenttasks",
            name=task_ref,
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            logger.warning(f"Parent task {task_ref} not found")
            return
        raise
    
    task_spec = task.get("spec", {})
    task_status = task.get("status", {})
    max_retries = task_spec.get("maxRetries", 3)
    retry_count = task_status.get("retryCount", 0)
    
    # Get the run to extract result/error
    run = api.get_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="agentruns",
        name=name,
    )
    run_status = run.get("status", {})
    
    if new == "Completed":
        # Task succeeded
        patch = {
            "status": {
                "phase": "Completed",
                "result": run_status.get("result"),
                "completionTime": datetime.now(timezone.utc).isoformat(),
            }
        }
    elif new == "Failed":
        if retry_count < max_retries:
            # Retry the task
            new_run_name = f"{task_ref}-run-{retry_count + 2}"
            run_body = {
                "apiVersion": f"{API_GROUP}/{API_VERSION}",
                "kind": "AgentRun",
                "metadata": {
                    "name": new_run_name,
                    "namespace": namespace,
                    "labels": {
                        "ai.adk.io/agent": spec.get("agentRef"),
                        "ai.adk.io/task": task_ref,
                    },
                },
                "spec": {
                    "agentRef": spec.get("agentRef"),
                    "taskRef": task_ref,
                    "goal": task_spec.get("goal"),
                    "context": task_spec.get("context", {}),
                    "maxSteps": spec.get("maxSteps", 10),
                    "timeout": spec.get("timeout", 300),
                },
            }
            
            api.create_namespaced_custom_object(
                group=API_GROUP,
                version=API_VERSION,
                namespace=namespace,
                plural="agentruns",
                body=run_body,
            )
            
            patch = {
                "status": {
                    "phase": "Running",
                    "currentRun": new_run_name,
                    "retryCount": retry_count + 1,
                }
            }
            logger.info(f"Retrying task {task_ref}, attempt {retry_count + 2}")
        else:
            # Max retries exceeded
            patch = {
                "status": {
                    "phase": "Failed",
                    "error": run_status.get("error", "Unknown error"),
                    "completionTime": datetime.now(timezone.utc).isoformat(),
                }
            }
            logger.error(f"Task {task_ref} failed after {max_retries} retries")
    
    # Patch the task status
    api.patch_namespaced_custom_object_status(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="agenttasks",
        name=task_ref,
        body=patch,
    )
