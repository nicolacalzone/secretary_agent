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
    FunctionTool
)

from tools.calendar_tools import is_it_holiday 

# Import LoggingPlugin for observability (like Kaggle notebook)
from google.adk.plugins import LoggingPlugin

# Import the calendar_agent from the agents package
from agents.calendar_agent import calendar_agent, find_slot_agent, treatment_information_agent

import os
from dotenv import load_dotenv

load_dotenv()

model_name = os.getenv("GOOGLE_LLM_MODEL", "gemini-2.5-flash-lite")

general_agent = LlmAgent(
    name="booking_assistant",
    model=Gemini(model=model_name, retry_options=retry_config),
    instruction="""You are a Booking assistant coordinator. Route requests to specialized agents if necessary and relay their responses.
    When the user denotes a date, always pass it to the calendar_agent to validate and standardize it.

    ROUTING RULES (choose one):
    
    Pass the control to calendar_agent if the user starts with booking related requests. 

    1. BOOKING/RESCHEDULING/CANCELLING → calendar_agent
       - Booking new appointments
       - Rescheduling existing appointments  
       - Cancelling appointments
       
       calendar_agent workflow:
       - Collects: date, time, treatment, name, email, phone
       - Validates all required fields present
       - Delegates to AppointmentCRUD for execution
       
    2. AVAILABILITY/TREATMENT QUERIES → treatment_information_agent
       - "What treatments are available?"
       
    3. DATE/TIME QUESTIONS → calendar_agent   
       - "Show me slots on [date]"
       - "When's the next available slot?"
       - Read-only queries about schedule
       - "What day is today?"
       - "When is next Monday?"
       - Date parsing and validation
       
       Important: If the user started the booking process, route to calendar_agent for consistency.
    
    RESPONSE PROTOCOL:
    - Always relay the actual response from delegated agent
    - Never invent, assume, or fabricate results
    - Always respond with text after delegation
    """,
    tools=[AgentTool(agent=calendar_agent), AgentTool(agent=treatment_information_agent)],
)

# NEW: Wrap in resumable App with LoggingPlugin for observabilit
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


