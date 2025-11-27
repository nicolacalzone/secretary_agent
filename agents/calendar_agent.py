"""
@DOCS
The calendar_agent is responsible for managing database interactions related 
to client and treatment information.
It provides functionalities to add new clients, retrieve client details, 
and list available treatments from the database.

The agent uses Google Calendar API to manage appointments including booking, 
rescheduling, and cancelling. It uses two SubAgents:

    1. CorrectorAgent: Validates and formats date/time inputs into ISO format.
    2. AppointmentCRUD: Handles appointment operations (insert, delete, move) in Google Calendar.

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
    find_next_available_slot
)

# 1. Specialist Agent for Date/Time Parsing and Validation
corrector_agent = LlmAgent(
    name="CorrectorAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Parse and validate date/time expressions. Always respond with text after using tools.
    
    Process:
    1. Extract date part from input ("tomorrow", "next Tuesday", "December 5", "28 11 2025", etc.)
       - Call parse_date_expression tool with ONLY the date portion
       - For "tomorrow at 10:00", pass "tomorrow" to the tool
       - For "28 11 2025 at 13:00", pass "28 11 2025" to the tool
    
    2. Extract and convert time to 24-hour HH:MM format:
       - "1.00", "1:00", "1" → "01:00"
       - "10.00", "10:00", "10" → "10:00"
       - "3pm", "15:00" → "15:00"
       - "1pm", "1 pm" → "13:00"
       - Default to "09:00" if no time specified
    
    3. Output format: "Validated date: YYYY-MM-DD, time: HH:MM"
    
    Examples:
    - "tomorrow at 3pm" → Call parse_date_expression("tomorrow") → "Validated date: 2025-11-28, time: 15:00"
    - "tomorrow at 1.00" → Call parse_date_expression("tomorrow") → "Validated date: 2025-11-28, time: 01:00"
    - "tomorrow at 10" → Call parse_date_expression("tomorrow") → "Validated date: 2025-11-28, time: 10:00"
    - "next Tuesday" → Call parse_date_expression("next Tuesday") → "Validated date: 2025-12-03, time: 09:00"
    - "28 11 2025 at 13:00" → Call parse_date_expression("28 11 2025") → "Validated date: 2025-11-28, time: 13:00"
    
    CRITICAL: Always use parse_date_expression for the date part, then parse time separately.
    """,
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression)
    ]
)

# 2. Specialist Agent for Finding Available Slots
find_slot_agent = LlmAgent(
    name="FindAvailableSlotAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Find the next available calendar slot and respond with text.
    
    Call find_next_available_slot, then respond:
    - If found: "✅ The next available slot is on YYYY-MM-DD at HH:MM"
    - If not found: "❌ No available slots found in the next 10 hours"
    """,
    tools=[
        FunctionTool(func=find_next_available_slot)
    ]
)

# 3. Specialist Agent for Availability Checking
availability_agent = LlmAgent(
    name="AvailabilityAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Check calendar availability and respond with text.
    
    Call check_availability, then respond based on status:
    - approved: "✅ The time slot is available"
    - pending: "⏸️ The slot is occupied. Alternative suggested. Please respond yes or no."
    - rejected: "❌ The slot is not available"
    """,
    tools=[
        FunctionTool(func=check_availability)
    ]
)

# 4. Specialist Agent for Appointment Operations
appointment_crud_agent = LlmAgent(
    name="AppointmentCRUD",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Handle appointment operations. Always verify required parameters before calling tools and respond with text.
    
    INSERT (booking) - REQUIRED: full_name, email, phone, date, time
    - If missing params, respond: "I need [missing params] to complete the booking"
    - Call insert_appointment only when all 5 params are present
    - Respond: "✅ Appointment booked for [name] on [date] at [time]" or "❌ Booking failed: [reason]"
    
    DELETE (canceling) - REQUIRED: email OR phone
    - If both missing, respond: "I need your email or phone number to cancel the appointment"
    - Call delete_appointment only when identifier is present
    - Respond: "✅ Appointment cancelled successfully" or "❌ No appointment found"
    
    MOVE (rescheduling) - REQUIRED: (email OR phone) AND new_date AND new_time
    - If missing params, respond: "I need [missing params] to reschedule"
    - Call move_appointment only when all required params are present
    - Respond: "✅ Rescheduled to [date] at [time]", "⏸️ Alternative suggested, respond yes/no", or "❌ Failed: [reason]"
    """,
    tools=[
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment)
    ]
)

# 5. Main Orchestrator Agent
calendar_agent = LlmAgent(
    name="CalendarAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You are a Calendar coordinator for appointment bookings.

    PRIVACY: Never reveal other people's appointment details. Only say the slot is "occupied" or "available".
    
    ═══════════════════════════════════════════════════════════════════════════
    BOOKING WORKFLOW:
    ═══════════════════════════════════════════════════════════════════════════
    1. VALIDATE DATE/TIME: Delegate to CorrectorAgent to parse expressions
       Extract "YYYY-MM-DD, time: HH:MM" date from response
    
    2. CHECK AVAILABILITY: Call check_availability(date, time) - MANDATORY
       - status='approved' → Slot is FREE, proceed to step 3
       - status='pending' → Slot OCCUPIED, inform user about alternative and STOP
         "I'm sorry, but [time] on [date] is occupied. Alternative: [alternative_time] on [alternative_date]. Book that instead?"
       - status='rejected' → No alternatives available, ask user for different time and STOP
    
    3. BOOK: Delegate to AppointmentCRUD with: full_name, email, phone, date, time
    
    4. CONFIRM: Provide clear confirmation to user
    
    ═══════════════════════════════════════════════════════════════════════════
    CANCELLING WORKFLOW:
    ═══════════════════════════════════════════════════════════════════════════
    1. If missing email AND phone, ask user for identifier and STOP
    2. Call delete_appointment with email/phone
    3. Confirm cancellation
    
    ═══════════════════════════════════════════════════════════════════════════
    RESCHEDULING WORKFLOW:
    ═══════════════════════════════════════════════════════════════════════════
    1. If missing email OR phone, ask user for identifier and STOP
    2. Validate new date/time with CorrectorAgent
    3. Call move_appointment(email=..., phone=..., new_date=..., new_time=...)
       (Tool handles availability checking and may pause for user confirmation)
    
    ═══════════════════════════════════════════════════════════════════════════
    KEY RULES:
    ═══════════════════════════════════════════════════════════════════════════
    - Always delegate date parsing to CorrectorAgent
    - Always delegate operations to AppointmentCRUD agent
    - Collect email/phone before calling move_appointment or delete_appointment
    - When status='pending', inform user and wait for yes/no response
    """,

    tools = [
        AgentTool(agent=corrector_agent),
        FunctionTool(func=check_availability),
        AgentTool(agent=appointment_crud_agent),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment),
        AgentTool(agent=find_slot_agent)
    ]
)


