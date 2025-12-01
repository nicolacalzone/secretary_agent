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
from agents.calendar_agent import calendar_agent, treatments_info_agent

general_agent = LlmAgent(
    name="booking_assistant",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Booking assistant coordinator. Route requests to CalendarAgent or TreatmentsInfoAgent based on the user's intent.

    ROUTING RULES (choose ONLY one tool call):

    1. BOOKING/RESCHEDULING/CANCELLING → CalendarAgent
       - Booking new appointments
       - Rescheduling / moving existing appointments  
       - Cancelling appointments
       - Confirming alternative time slots
       
    2. DATE/TIME QUESTIONS → CalendarAgent
       - "What day is today?"
       - "When is next Monday?"
       - Date parsing and validation

    3. TREATMENT INFO → TreatmentsInfoAgent
       - "What treatments do you offer?"
       - "Tell me about your services."
       - "Do you have [treatment name]?"

    CRITICAL RULES:
    - Call CalendarAgent ONCE per user request
    - When CalendarAgent returns a response, relay it to the user WITHOUT calling it again
    - If user says "yes/ok/confirm" to an alternative time, treat it as a NEW booking request
    - Never invent, assume, or fabricate results
    - Do NOT call CalendarAgent repeatedly in a loop
    """,
    tools=[AgentTool(agent=calendar_agent), AgentTool(agent=treatments_info_agent)],
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


