#!/usr/bin/env python3
"""
ADK Controller - Main Entry Point

This controller watches for Agent, AgentTask, and AgentRun CRDs
and orchestrates the execution of AI agents.
"""

import asyncio
import logging
import os
import sys

import kopf
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Import handlers - they register themselves with kopf
from controller.handlers import agent_handler, task_handler, run_handler
from controller.services.config import Config


def main():
    """Main entry point for the controller."""
    
    # Load configuration
    config = Config.from_env()
    logger.info("Starting ADK Controller", 
                vllm_endpoint=config.vllm_endpoint,
                namespace=config.namespace)
    
    # Configure kopf settings
    kopf_settings = kopf.OperatorSettings()
    kopf_settings.posting.level = logging.WARNING
    kopf_settings.watching.connect_timeout = 60
    kopf_settings.watching.server_timeout = 300
    
    # Run the operator
    kopf.run(
        clusterwide=False,
        namespace=config.namespace if config.namespace else None,
        standalone=True,
        settings=kopf_settings,
    )


if __name__ == "__main__":
    main()
