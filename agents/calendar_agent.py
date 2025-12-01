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
    SequentialAgent,
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
    2.  Call parse_date_expression() on the date given by the user to resolve to ISO date
        - AM: 12 AM→00:00, 1-11 AM→01:00-11:00
        - PM: 12 PM→12:00, 1-11 PM→13:00-23:00
    3. Always outputs the normalized date and time in YYYY-MM-DD, time: HH:MM format.
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
     instruction="""Find available appointment slots.
    
    Workflow:
        1. If the user provides a relative date (e.g., "tomorrow", "next Monday"), use CorrectorAgent to parse it into ISO format.
        2. Execute appropriate query based on the request:
           - All slots on a specific date → return_available_slots(iso_date)
           - Next available slot after a specific time → find_next_available_slot(iso_date, time)
           - Check if a specific slot is available → check_availability(iso_date, time)
        3. Provide a clear, formatted response containing the available slots.
    """,
    tools=[
        AgentTool(agent=corrector_agent),
        FunctionTool(func=find_next_available_slot),
        FunctionTool(func=return_available_slots),
        FunctionTool(func=check_availability),
    ]
)

# 3. Specialist Agent for Appointment Operations
appointment_crud_agent = LlmAgent(
    name="AppointmentCRUD",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Execute appointment operations with availability validation.
    
    This agent handles booking, canceling, and rescheduling appointments.
    It receives date/time directly as parameters (can be relative like "tomorrow" or absolute).
    
    CRITICAL WORKFLOW:
    Before insert_appointment() or move_appointment():
    
    Step 1: PARSE DATE - ALWAYS DO THIS FIRST
    - ALWAYS call get_current_date() first to get today's date
    - If date contains words like "tomorrow", "today", "next Monday", "in 3 days", etc:
      → MUST call parse_date_expression(date_string) to convert to ISO format YYYY-MM-DD
      → Example: parse_date_expression("tomorrow") → "2025-12-02"
    - If date is already in YYYY-MM-DD format, verify it's not in the past by checking get_current_date()
    - Extract the ISO date from the parse result
    
    Step 2: NORMALIZE TIME
    - Ensure time is in HH:MM format (24-hour)
    - Convert "11am" → "11:00", "3pm" → "15:00"
    
    Step 3: CHECK AVAILABILITY
    - Call check_availability(iso_date, normalized_time) using the parsed values
    - Handle the response based on status:
       
       a) If status == 'approved' and is_available == True:
          → ONLY NOW proceed with insert_appointment() or move_appointment()
       
       b) If status == 'pending':
          → The slot is OCCUPIED - DO NOT call insert_appointment()!
          → An alternative_date and alternative_time are suggested
          → Verify alternative: call check_availability(alternative_date, alternative_time)
          → If alternative shows status == 'approved': offer it to user
             "The requested time [original] is occupied. Would you like [alternative_date] at [alternative_time] instead?"
          → If alternative also occupied: call find_next_available_slot() and offer that
          → WAIT for user confirmation before booking any alternative
       
       c) If status == 'rejected':
          → DO NOT call insert_appointment()!
          → The time is outside business hours or another error occurred
          → Respond with the error message from the tool
    
    Required parameters:
    - insert: full_name, email, phone, date, time, treatment (optional)
    - delete: email OR phone
    - move: email OR phone + new_date + new_time

    Do NOT attempt an insert unless ALL of these are present and non-empty!
    
    CRITICAL RULES:
    1. ALWAYS parse dates using get_current_date() and parse_date_expression() BEFORE checking availability
    2. NEVER use hardcoded dates - always parse relative date expressions
    3. NEVER call insert_appointment() or move_appointment() if check_availability() returns status 'pending' or 'rejected'
    4. ONLY call insert_appointment() when check_availability() returns status 'approved' with is_available == True
    5. For pending/rejected status, offer alternatives but DO NOT book without user confirmation
    
    POST-OPERATION, WRITE A FINAL MESSAGE:
    - Insert: "Appointment booked for [full_name] on [date] at [time]. Calendar link: [public_add_link]"
    - Delete: "Appointment cancelled."
    - Move: "Appointment rescheduled for [full_name] to [date] at [time]. Calendar link: [public_add_link]"
    - Pending/Alternative: "The requested time is occupied. [Alternative time offer]"
    - Unavailable: "That slot is unavailable. Please choose another time."
    - Missing params: "I need [missing info]."
    """,
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression),
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment),
        FunctionTool(func=check_availability),
        FunctionTool(func=find_next_available_slot)
    ]
)

# 4. Specialist Agent for Treatment Information
treatments_info_agent = LlmAgent(
    name="TreatmentsInfoAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
     instruction="""Provide information about available treatments and appointment slots.  
    
     IF asked about all available treatments:
        - call the check_treatment_type() tool which returns a list of all available treatments.

    ELSE IF asked about a specific treatment:
        - call the check_treatment_type([treatment_name]) tool which returns if [treatment_name] is available.

    It returns the list of available treatments or availability status [TRUE, FALSE] of the specific treatment.
    """,
    tools=[
        FunctionTool(func=check_treatment_type)
    ]
)


# 5. Main Orchestrator Agent
calendar_agent = LlmAgent(
    name="CalendarAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Calendar orchestrator that manages appointment bookings and queries.

    AVAILABLE TOOLS:
     - CorrectorAgent: Parse date expressions (e.g., "tomorrow", "next Monday") into normalized format
        * Use when: user provides a relative date that needs parsing
     
     - FindAvailableSlotAgent: Query available appointment slots
        * Use for: finding available slots, checking specific dates, "earliest possible" requests
     
     - AppointmentCRUD: Complete booking workflow (can parse dates + perform operation)
        * Use for: booking appointments, cancelling, rescheduling
        * Pass: full_name, email, phone, date (can be "tomorrow"), time, treatment
        * This agent can parse relative dates like "tomorrow" and perform the booking

    BOOKING FLOW:
    1) COLLECT required information by asking the user:
        - Date/time: If not provided, ask "When would you like to book?"
        - Treatment: Ask if not mentioned, default to "General Consultation"
        - Contact: full_name, email, phone
        
    2) Once ALL information is collected:
        - Call AppointmentCRUD ONCE with: full_name, email, phone, date (raw like "tomorrow"), time, treatment
        - The agent will parse dates internally if needed and perform the booking
        - Present the result to the user EXACTLY as returned by AppointmentCRUD
        - DO NOT call AppointmentCRUD again - just relay the message
        
    3) If AppointmentCRUD returns an alternative time offer:
        - Pass it to the user VERBATIM
        - DO NOT call any tools again
        - Let the user respond with confirmation or new request
    
    QUERY FLOW:
    - For "earliest possible/ASAP/soonest" → call FindAvailableSlotAgent
    - For "available on [date]" → call FindAvailableSlotAgent
    - For date parsing only → call CorrectorAgent

    CRITICAL: 
    - Call AppointmentCRUD only ONCE per booking request
    - Do NOT re-call AppointmentCRUD when relaying its response to the user
    - If user says "yes" to an alternative time, treat it as a NEW booking request with the alternative time
    """,
    tools=[
        AgentTool(agent=corrector_agent),
        AgentTool(agent=find_slot_agent),
        AgentTool(agent=appointment_crud_agent)
    ]
)

