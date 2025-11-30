import os
import asyncio
import logging
from typing import Dict, Any

# Import all ADK dependencies from shared module (imported once in __init__.py)
from . import (
    LlmAgent,
    Gemini,
    AgentTool,
    retry_config,
    Runner,
    InMemorySessionService,
    App,
    ResumabilityConfig,
    LoggingPlugin,
    InMemoryMemoryService,
    ContextCacheConfig
)

# Import LoggingPlugin for observability (like Kaggle notebook)
from google.adk.plugins import LoggingPlugin

# Import the calendar_agent from the agents package
from agents.calendar_agent import calendar_agent, find_slot_agent

root_agent = LlmAgent(
    name="booking_assistant",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You are a Booking assistant coordinator. Route requests to specialized agents if necessary and relay their responses.

    ROUTING RULES (choose one):

    1. BOOKING/RESCHEDULING/CANCELLING → calendar_agent
       - Booking new appointments
       - Rescheduling existing appointments  
       - Cancelling appointments
       
       calendar_agent workflow:
       - Collects: date, time, treatment, name, email, phone
       - Validates all required fields present
       - Delegates to AppointmentCRUD for execution
       
    2. AVAILABILITY/TREATMENT QUERIES → find_slot_agent
       - "What treatments are available?"
       - "Show me slots on [date]"
       - "When's the next available slot?"
       - Read-only queries about schedule
       
    3. DATE/TIME QUESTIONS → calendar_agent
       - "What day is today?"
       - "When is next Monday?"
       - Date parsing and validation
    
    RESPONSE PROTOCOL:
    - Always relay the actual response from delegated agent
    - Never invent, assume, or fabricate results
    - Always respond with text after delegation
    """,
    tools=[AgentTool(agent=calendar_agent), AgentTool(agent=find_slot_agent)],
)

# NEW: Wrap in resumable App with LoggingPlugin for observability
app = App(
    name="agents",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
    plugins=[LoggingPlugin()],  # Add logging plugin here for comprehensive observability
    context_cache_config=ContextCacheConfig(
        min_tokens=2048,    # Minimum tokens to trigger caching
        ttl_seconds=600,    # Store for up to 10 minutes
        cache_intervals=5,  # Refresh after 5 uses
    ),
)

# Create session service and runner
session_service = InMemorySessionService()
runner = Runner(
    app=app,  # Pass app instead of agent
    session_service=session_service,
    memory_service=InMemoryMemoryService() 
)


