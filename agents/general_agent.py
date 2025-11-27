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
    Runner, #for workflow
    InMemorySessionService,
    App,
    ResumabilityConfig,
    LoggingPlugin
)

# Import the calendar_agent from the agents package
from agents.calendar_agent import calendar_agent

general_agent = LlmAgent(
    name="booking_assistant",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You are a booking assistant for a doctor's studio.
        You can help users book, reschedule, or cancel appointments using the calendar_agent tool.
        Always use the calendar_agent tool to interact with the calendar.
        Be polite and concise in your responses.

        Ask for Full Name, Phone Number, Email, Preferred Date & Time for the appointment, and for the Treatment Type when booking.
    """,
    tools=[AgentTool(agent=calendar_agent)],
)

# NEW: Wrap in resumable App
general_app = App(
    name="booking_coordinator",
    root_agent=general_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
    plugins=[LoggingPlugin()]  # Enable logging plugin
)

# Create session service and runner
session_service = InMemorySessionService()
general_runner = Runner(
    app=general_app,  # Pass app instead of agent
    session_service=session_service
)


