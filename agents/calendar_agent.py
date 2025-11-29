"""
Calendar Agent Module - Google Calendar API Integration

This module manages appointment operations using Google Calendar API with a 
clean multi-agent architecture:

Agent Hierarchy:
    1. CorrectorAgent: Parses date expressions and normalizes time formats
    2. FindAvailableSlotAgent: Queries available slots and treatment information (read-only)
    3. AppointmentCRUD: Executes all CRUD operations (insert, delete, move) with availability checking
    4. CalendarAgent: Main orchestrator coordinating SubAgents for booking workflows

Workflow:
    Booking → CalendarAgent collects info → validates completeness → delegates to AppointmentCRUD
    Queries → CalendarAgent uses direct tools or delegates to FindAvailableSlotAgent
    Date parsing → Always via CorrectorAgent
    CRUD operations → Always via AppointmentCRUD (includes availability checks)
"""


from . import (
    LlmAgent,
    Gemini,
    AgentTool,
    retry_config,
    FunctionTool,
)

from tools.calendar_tools import (
    insert_appointment,
    delete_appointment,
    move_appointment,
    get_current_date,
    parse_date_expression,
    check_availability,
    find_next_available_slot,
    check_treatment_type,
    return_available_slots
)

# 1. Specialist Agent for Date/Time Parsing and Validation
corrector_agent = LlmAgent(
    name="CorrectorAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Parse date expressions into ISO format (YYYY-MM-DD) and normalize time to 24-hour format.

    Process:
    1. Call get_current_date() to establish reference date
    2. Call parse_date_expression() with user's date input
    3. Convert time to 24-hour format (default "09:00" if not provided):
       - AM: 12 AM→00:00, 1-11 AM→01:00-11:00
       - PM: 12 PM→12:00, 1-11 PM→13:00-23:00
    4. Always respond with text: "Validated date: YYYY-MM-DD, time: HH:MM"
    """,
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression)
    ]
)

# 2. Specialist Agent for Finding Available Slots and Treatment Info
find_slot_agent = LlmAgent(
    name="FindAvailableSlotAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Find available appointment slots and treatment information.
    
    Workflow:
    1. Parse any relative dates ("today", "tomorrow") using parse_date_expression()
    2. Execute appropriate query:
       - List treatments → check_treatment_type()
       - Slots on date → return_available_slots(iso_date)
       - Next slot after time → find_next_available_slot(iso_date, time)
    3. Provide clear, formatted response
    """,
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression),
        FunctionTool(func=find_next_available_slot),
        FunctionTool(func=check_treatment_type),
        FunctionTool(func=return_available_slots)
    ]
)

# 3. Specialist Agent for Appointment Operations
appointment_crud_agent = LlmAgent(
    name="AppointmentCRUD",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Execute appointment operations with availability validation.
    
    CRITICAL WORKFLOW:
    Before insert_appointment() or move_appointment():
    1. ALWAYS call check_availability(date, time) FIRST
    2. If busy → respond "That slot is unavailable. Please choose another time."
    3. If available → proceed with operation
    
    Required parameters:
    - insert: full_name, email, phone, date, time, treatment (optional)
    - delete: email OR phone
    - move: (email OR phone) + new_date + new_time
    
    Confirmation messages:
    - Insert: "Appointment booked for [name] on [date] at [time]!"
    - Delete: "Appointment cancelled."
    - Move: "Appointment rescheduled to [date] at [time]."
    - Unavailable: "That slot is unavailable. Please choose another time."
    - Missing params: "I need [missing info]."
    """,
    tools=[
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment),
        FunctionTool(func=check_availability)
    ]
)

# 4. Main Orchestrator Agent
calendar_agent = LlmAgent(
    name="CalendarAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Coordinate calendar bookings using conversation memory. Always respond after tool calls.

    CONVERSATION MEMORY:
    Review conversation history before asking questions. Build on existing information - never re-ask what user already provided.

    BOOKING WORKFLOW (3 stages - must complete in order):
    
    Stage 1 - COLLECTION:
    Gather all required information:
    - Date: delegate to CorrectorAgent for parsing (handles "today", "tomorrow", etc.)
    - Time: ask if missing (default: 09:00)
    - Treatment: default to "General Consultation" if not mentioned
    - Contact: name, email, phone
    
    Stage 2 - VALIDATION:
    Verify ALL required fields present: date, time, name, email, phone
    NEVER proceed to Stage 3 without all five fields.
    
    Stage 3 - EXECUTION:
    Delegate complete information to AppointmentCRUD (it will check availability and book)

    OTHER OPERATIONS (always via AppointmentCRUD):
    - Cancel: delegate to AppointmentCRUD with email OR phone
    - Reschedule: delegate to AppointmentCRUD with (email OR phone) + new_date + new_time
    
    Query tools (use directly without delegation):
    - Current date: get_current_date()
    - Treatments list: check_treatment_type()
    - Available slots: return_available_slots(date)
    """,

    tools = [
        FunctionTool(func=get_current_date),
        AgentTool(agent=corrector_agent),
        AgentTool(agent=appointment_crud_agent),
        FunctionTool(func=check_treatment_type),
        FunctionTool(func=return_available_slots)
    ]
)


