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
)

# Import LoggingPlugin for observability (like Kaggle notebook)
from google.adk.plugins import LoggingPlugin

# Import the calendar_agent from the agents package
from agents.calendar_agent import calendar_agent, find_slot_agent

general_agent = LlmAgent(
    name="booking_assistant",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Booking assistant coordinator. Route requests to specialized agents and relay their responses.

    ROUTING RULES (choose one):

    1. BOOKING/RESCHEDULING/CANCELLING → calendar_agent
       - Booking new appointments
       - Rescheduling existing appointments  
       - Cancelling appointments
       
       calendar_agent workflow:
       - Collects: date, time, treatment, name, email, phone
       - Validates all required fields present
       - Delegates to AppointmentCRUD for execution
       
        2. AVAILABILITY/TREATMENT QUERIES → find_slot_agent (ALWAYS answer even mid booking)
       - "What treatments are available?"
       - "Show me slots on [date]"
       - "When's the next available slot?"
       - Read-only queries about schedule

        INTERRUPT OVERRIDE:
            If user asks for "slots", "availability", "available times", "next slot", or treatments list while in the middle of collecting booking info → temporarily delegate to find_slot_agent, return its answer, then resume booking collection.
            Never withhold availability info due to missing contact details.
       
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
general_app = App(
    name="agents",
    root_agent=general_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
    plugins=[LoggingPlugin()]  # Add logging plugin here for comprehensive observability
)

# Create session service and runner
session_service = InMemorySessionService()
general_runner = Runner(
    app=general_app,  # Pass app instead of agent
    session_service=session_service,
    memory_service=InMemoryMemoryService() 
)


