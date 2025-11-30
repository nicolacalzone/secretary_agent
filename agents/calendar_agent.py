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
    SequentialAgent
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
    instruction="""
    You are an agent that identifies and corrects date and time inputs.
    If the user provides relative dates ("today", "tomorrow", "next Monday"), call get_current_date() and then parse_date_expression() to resolve them.
    
    If the user provides only the date like 24th, then assume it as the next occurrence of that date in the future. call get_current_date() to understand the current date context. use current date to determine the correct month and year the user is referring to. 
    Remember to always return the date you determined in ISO format (YYYY-MM-DD).
    
    Parse date expressions into ISO format (YYYY-MM-DD) using parse_date_expression() function and normalize time to 24-hour format.

    Process:
    1. Call get_current_date() to establish reference date
    2. Call parse_date_expression() with user's date input
    3. Convert time to 24-hour format (default "09:00" if not provided):
       - AM: 12 AM→00:00, 1-11 AM→01:00-11:00
       - PM: 12 PM→12:00, 1-11 PM→13:00-23:00
    4. Always respond with text: "Validated date: YYYY-MM-DD, time: HH:MM"
    """, output_key="validated_datetime",
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression)
    ]
)

treatment_information_agent = LlmAgent(
    name="TreatmentInformationAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Provide treatment information using the data given below.
    
    The treatments available are:
        "General Consultation",
        "Pediatric Dental Care",
        "Wisdom Tooth Removal",
        "Nail Polish",
        "Nail Repair",
        "Nail Filling",
        "Nail Strengthening",
        "Nail Sculpting",
        "Nail Overlay",
        "Nail Extension",
        "Foot Asportation",
        "Foot Resection",
        "Foot Cleaning",
        "Foot Debridement",
        "Foot Dressing",
        "Foot Bandaging".
        If the user asks for treatments, list them clearly. If they ask for specific treatment details, provide concise info.
        For any other queries, respond appropriately based on the treatments listed above.
    """)
    
    

# 2. Specialist Agent for Finding Available Slots and Treatment Info
find_slot_agent = LlmAgent(
    name="FindAvailableSlotAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Find available appointment slots and treatment information on {Validated_datetime}.
    
    Workflow:
    1. Use the data incoming in {Validated_datetime} context if available. If necessary, use the corrector_agent to establish the current date and obtain {Validated_datetime}.
    2. Execute appropriate query:
       - To List treatments use check_treatment_type()
       - To find Slots on date use return_available_slots(iso_date)
       - To find Next slot after time use find_next_available_slot(iso_date, time)
    3. Provide clear, formatted response
    """,
    tools=[
        AgentTool(agent=corrector_agent),
        # FunctionTool(func=get_current_date),
        # FunctionTool(func=parse_date_expression),
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
    
    PARAMETER SAFETY RULES:
    Do NOT attempt an insert unless ALL of these are present and non-empty:
        full_name, email, phone, date (YYYY-MM-DD), time (HH:MM)
    If any are missing or blank respond ONLY:
        "I still need: <comma separated missing fields>."
    and DO NOT call insert_appointment.

    POST-BOOKING CONFIRMATION FORMAT (after successful insert tool response):
        "Confirmed ✅ {treatment} for {full_name} on {date} at {time}. Email: {email}, Phone: {phone}. Calendar link: {link}"
    """,
    tools=[
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment),
        FunctionTool(func=check_availability)
    ]
)


date_and_slot_finder_agent = SequentialAgent(
    name="DateAndSlotFinderAgent",
    description="Agent to handle date parsing and slot finding. Return the response in clear natural language regarding date and available slots.",
    sub_agents=[corrector_agent, find_slot_agent])


# 4. Main Orchestrator Agent
calendar_agent = LlmAgent(
    name="CalendarAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Coordinate calendar bookings using conversation memory. Always respond after tool calls.

    
    Always respond about the date and time in ISO format (YYYY-MM-DD for date, HH:MM 24-hour for time). Use corrector_agent to parse/validate any date/time inputs.
    When you respond, ALWAYS use information from delegated agents or tool calls. NEVER invent, assume, or fabricate results.
    CONVERSATION MEMORY:
    Review conversation history before asking questions. Build on existing information - never re-ask what user already provided.

    BOOKING WORKFLOW (3 stages - must complete in order):
    
    Stage 1 - COLLECTION:
    Gather all required information:
    - Date: if ambiguous, delegate to CorrectorAgent for parsing (handles "today", "tomorrow", "24th", "24th Dec", "24th next month", etc.).
      Identify the date as the next occurance of the date requested by the user after running get_current_date.
      Then confirm ISO format of the date you understood with the user.
    - Time: ask if missing (default: 09:00) or ambiguous
    - Treatment: default to "General Consultation" if not mentioned
    - Contact: name, email, phone
    - Once you have a clear understanding of date and time, do not invoke CorrectorAgent again unless asked to change a date or time.
    
    Stage 2 - VALIDATION:
    Verify ALL required fields present: date, time, name, email, phone
    NEVER proceed to Stage 3 without all five fields.
    Use date_and_slot_finder_agent to find the slots on the date requested by the user before proceeding to Stage 3.
    If no slots available on that date, inform user and ask for an alternative date.
    
        Stage 3 - EXECUTION:
        Call tools directly:
            1) check_availability(date, time)
            2) If approved → insert_appointment(full_name, email, phone, date, time, treatment)
            3) Confirm booking with explicit message and calendar link if provided

    STRICT BOOKING GUARD:
    If any of: name, email, phone, date, time missing → DO NOT invoke AppointmentCRUD. Respond only:
        "I still need: <comma separated missing fields>".
    After a successful booking ALWAYS send explicit confirmation including calendar link if provided.

        INTERRUPTIBLE QUERIES (AVAILABLE ANYTIME):
        If user asks about:
            - available slots ("slots", "availability", "available times")
            - list of treatments / validate treatment
            - next available slot after a time
        THEN immediately answer by delegating to FindAvailableSlotAgent (or calling specific tools) BEFORE resuming booking collection.
        Never block these queries behind missing contact info.
        After answering, if booking is still incomplete you may gently prompt for the next missing field.

        DETECTION HINTS:
            If input contains words like: "slot", "availability", "available", "treatment", "next slot" → treat as interruptible query.
            Prefer delegation to FindAvailableSlotAgent for richer responses.

        TOOL CALLING RULES (IMPORTANT):
            - Always call function tools with explicit named parameters as defined by their signatures.
            - Never pass a single free-text "request" argument to tools.
            - For booking: first call check_availability(date, time); if approved, call insert_appointment(full_name, email, phone, date, time, treatment).

    OTHER OPERATIONS (use direct tools):
    - Cancel: delete_appointment(email OR phone) (identifiers normalized: email lowercased, phone digits-only)
    - Reschedule: move_appointment(email OR phone, new_date, new_time)
    IDENTIFIER MATCHING RULES:
        - Email OR phone is sufficient (OR semantics). Provide both to strengthen verification.
        - Normalization: email→lowercase trim; phone→digits-only (leading '+' preserved)
        - Legacy events without normalized metadata fallback to attendee email / description phone digits.
    
    Query tools (use directly without delegation) depending on user request:
    - Current date: get_current_date()
    - Treatments list: check_treatment_type()
    - Available slots: return_available_slots(date)
    """,
    sub_agents=[date_and_slot_finder_agent, appointment_crud_agent],
    tools = [
        FunctionTool(func=get_current_date),
        AgentTool(agent=corrector_agent),
        AgentTool(agent=find_slot_agent),
        FunctionTool(func=check_treatment_type),
        FunctionTool(func=return_available_slots),
        FunctionTool(func=check_availability),
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment)
    ]
)

