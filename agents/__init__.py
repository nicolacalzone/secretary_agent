"""
Shared imports and utilities for all agents
Import once here, use everywhere
"""

# Google ADK Core
from google.genai import types
from google.adk.agents import LlmAgent,SequentialAgent
from google.adk.models.google_llm import Gemini
#from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search, AgentTool
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.memory import InMemoryMemoryService
from google.adk.plugins.logging_plugin import (LoggingPlugin)
from google.adk.runners import Runner, InMemoryRunner
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.apps.app import App, ResumabilityConfig
from google.adk.tools.function_tool import FunctionTool
from google.adk.agents.context_cache_config import ContextCacheConfig

import uuid

# Shared configurations
retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

# Export everything for easy access
__all__ = [
    'types',
    'LlmAgent',
    'Gemini',
    'InMemoryRunner',
    'InMemorySessionService',
    'google_search',
    'AgentTool',
    'ToolContext',
    'BuiltInCodeExecutor',
    'retry_config',
    'InMemoryMemoryService'
]
