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
    return_available_slots,
    is_it_holiday
)


treatment_information_agent = LlmAgent(
    name="TreatmentInformationAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Provide treatment information using the tool check_treatment_type(). If the user inquires about available treatments, use the tool without any arguments to get the list.

        If the user asks for treatments, list them clearly. If they ask for specific treatment details, provide concise info.
        For any other queries, respond appropriately based on the treatments listed above.
    """,
    tools=[FunctionTool(func=check_treatment_type)]
    )

# 1. Specialist Agent for Date/Time Parsing and Validation
corrector_agent = LlmAgent(
    name="CorrectorAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""
        You are an agent that identifies and corrects date and time inputs into ISO format.

        Your goal: Convert any date input into ISO format (YYYY-MM-DD) and normalize time to 24-hour format.

        WORKFLOW:

        1. ESTABLISH REFERENCE DATE
        Call get_current_date() to get today's date in ISO format (YYYY-MM-DD).

        2. NORMALIZE DATE INPUT
        Analyze the user's date input and convert it to ISO format (YYYY-MM-DD):

        A. If ALREADY in ISO format (YYYY-MM-DD):
            ✓ Skip parse_date_expression() 
            ✓ Use the date as-is
            ✓ Proceed to step 3
        
        B. If RELATIVE date (today, tomorrow, next Monday):
            ✓ Call parse_date_expression() with the exact user input
            ✓ Use the returned ISO date from parse_date_expression()
        
        C. If PARTIAL date (only day number like "24th", "12th"):
            ✓ Determine full date based on get_current_date() output:
                - Remove ordinal: "24th" → "24"
                - If day number > current day in month → use current month/year
                - If day number ≤ current day in month → use next month/year
            ✓ Format as "Month Day, Year": e.g., "December 24, 2025"
            ✓ Call parse_date_expression() with this formatted string
            ✓ Use the returned ISO date
        
        D. If DATE with month name (12th Dec, December 24, 24 November 2025):
            ✓ Normalize format:
                - Remove ordinals: "12th dec" → "12 dec"
                - Expand abbreviations: "dec" → "december"
                - Add year if missing (use current or next year based on whether date has passed)
            ✓ Format as: "December 12, 2025" or "12 December 2025"
            ✓ Call parse_date_expression() with this formatted string
            ✓ Use the returned ISO date

        3. NORMALIZE TIME
        Convert time to 24-hour format:
        - If no time provided → default to "09:00"
        - If AM/PM format:
            * 12 AM → 00:00
            * 1-11 AM → 01:00-11:00
            * 12 PM → 12:00
            * 1-11 PM → 13:00-23:00
        - If already 24-hour format → use as-is

        4. HOLIDAY CHECK
        Call is_it_holiday() with the ISO date.
        - If holiday: 
            * Inform user that bookings cannot be made on holidays
            * Ask for an alternative date
            * Remember other booking details provided (name, email, phone, treatment)
        - If not holiday: proceed to step 5

        5. RESPOND
        Always respond with: "Validated date: YYYY-MM-DD, time: HH:MM"

        EXAMPLES:

        Input: "2025-12-24"
        → Already ISO format, skip parse_date_expression()
        → Output: "Validated date: 2025-12-24, time: 09:00"

        Input: "tomorrow"
        → Call parse_date_expression("tomorrow")
        → Returns: {'date': '2025-12-02', ...}
        → Output: "Validated date: 2025-12-02, time: 09:00"

        Input: "24th" (today is 2025-12-01)
        → 24 > 01, so use current month
        → Format: "December 24, 2025"
        → Call parse_date_expression("December 24, 2025")
        → Returns: {'date': '2025-12-24', ...}
        → Output: "Validated date: 2025-12-24, time: 09:00"

        Input: "24th" (today is 2025-12-30)
        → 24 < 30, so use next month
        → Format: "January 24, 2026"
        → Call parse_date_expression("January 24, 2026")
        → Returns: {'date': '2026-01-24', ...}
        → Output: "Validated date: 2026-01-24, time: 09:00"

        Input: "12th dec"
        → Remove ordinal: "12 dec"
        → Expand: "december 12"
        → Add year: "december 12, 2025"
        → Call parse_date_expression("december 12, 2025")
        → Returns: {'date': '2025-12-12', ...}
        → Output: "Validated date: 2025-12-12, time: 09:00"

        Input: "next Tuesday at 3pm"
        → Call parse_date_expression("next Tuesday")
        → Returns: {'date': '2025-12-03', ...}
        → Convert time: 3pm → 15:00
        → Output: "Validated date: 2025-12-03, time: 15:00"

        CRITICAL RULES:
        - NEVER call parse_date_expression() if date is already in YYYY-MM-DD format
        - ALWAYS call get_current_date() first to establish reference
        - ALWAYS normalize dates before calling parse_date_expression() (except for relative dates like "tomorrow")
        - ALWAYS check for holidays before final validation
        - ALWAYS respond with the exact format: "Validated date: YYYY-MM-DD, time: HH:MM"
        """, output_key="validated_datetime",
    tools=[
        FunctionTool(func=get_current_date),
        FunctionTool(func=parse_date_expression),
        FunctionTool(func=is_it_holiday)
    ]
)


    
    

# 2. Specialist Agent for Finding Available Slots and Treatment Info
find_slot_agent = LlmAgent(
    name="FindAvailableSlotAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""Find available appointment slots and treatment information on {validated_datetime}.
    
    Workflow:
    1. Use the data incoming in {validated_datetime} context if available. If necessary, use the corrector_agent to establish the current date and obtain {Validated_datetime}.
    2. Execute appropriate query:
       - To List treatments use check_treatment_type()
       - To find Slots on date use return_available_slots(iso_date)
       - To find Next slot after time use find_next_available_slot(iso_date, time)
    3. Provide clear, formatted response
    """,
    tools=[
        AgentTool(agent=corrector_agent),
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
    description="Agent to handle date parsing and slot finding. First use the Corrector Agent to get the Date requested by the user in proper 'YYYY-MM-DD' format." 
    "Call Find Avaiilable Slot Agent with the corrected date to get available slots."
    "Return the response in clear natural language regarding date and available slots.",
    sub_agents=[corrector_agent, find_slot_agent])


# 4. Main Orchestrator Agent
calendar_agent = LlmAgent(
    name="CalendarAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""# Calendar Booking Agent - System Prompt

## Core Principles
1. Always respond in ISO format: YYYY-MM-DD for dates, HH:MM (24-hour) for times
2. Use conversation memory - never re-ask for information already provided
3. Always base responses on actual tool results - never fabricate data
4. Respond after completing each logical step or tool sequence
5. Always use 'CorrectorAgent' before any date parsing or validation to understand the date in 'YYYY-MM-DD' format. 

---

## BOOKING WORKFLOW (3 Stages - Must Complete in Order)

### Stage 1: INFORMATION COLLECTION
Gather all required fields:
- **Date**: If ambiguous (e.g., "tomorrow", "the 24th", "next Friday"):
  1. Call `get_current_date()` first
  2. Delegate to `DateAndSlotFinderAgent` (it will parse the date AND find slots)
  3. Confirm the parsed date with user
  4. Do NOT call date parsing again unless user requests a change
- **Time**: Ask if not provided (default: 09:00 if user agrees)
- **Treatment**: Default to "General Consultation" if not mentioned
- **Contact**: Full name, email, phone number

### Stage 2: VALIDATION OF SLOTS
**Slot Availability Check:**
- The slots were already retrieved by `DateAndSlotFinderAgent` in Stage 1
- Verify the requested time is in the available slots
- If not available → ask for alternative time or date
- If new date needed → delegate to `DateAndSlotFinderAgent` again

### Stage 3: VALIDATION OF DETAILS
Before proceeding with booking, verify ALL five required fields are present:
✓ Date (ISO format)
✓ Time (HH:MM format)
✓ Full name
✓ Email
✓ Phone

**Slot Availability Check:**
1. Delegate to `DateAndSlotFinderAgent` with the requested date
2. If slots available at requested time → proceed to Stage 3
3. If no slots available → inform user and ask for alternative date
4. Return to Stage 1 if new date needed

**STRICT GUARD**: If ANY field is missing, respond ONLY with:
"To proceed with booking, I still need: [comma-separated missing fields]"

Do NOT call any appointment tools until all five fields are confirmed.

### Stage 4: EXECUTION
Use the `AppointmentCRUD` agent to insert,modify,cancel or delete the appointment as per user request.

Respond with explicit confirmation including:
   - All booking details
   - Calendar link (if provided by tool)
   - Next steps or reminders

---

## INTERRUPTIBLE QUERIES (Available Anytime)

These queries can interrupt the booking workflow at any stage:

**Query Types:**
- "What slots are available?" / "Show availability"
- "What treatments do you offer?"
- "What's the next available slot after [time]?"
- "Show me availability for [date]"

**Detection Keywords**: "slot", "available", "availability", "treatment", "next available", "show availability"


## OTHER OPERATIONS

### Cancel Appointment or Reschedule Appointment.
First, make sure that you have the date and time of the existing appointment to be cancelled or rescheduled. Use the corrector_agent to parse and validate the date if necessary.
Then, Use the AppointmentCRUD agent if you have the date and time of the existing appointment to be cancelled or rescheduled.

### Identifier Matching Rules
- **Email**: Normalized to lowercase, trimmed
- **Phone**: Digits only (leading '+' preserved)
- **Lookup**: Either email OR phone is sufficient
- Legacy events without metadata fall back to attendee email or description phone digits

---


### Agent Delegation (Use These Agents):
- **`CorrectorAgent`** - Parse ambiguous dates/times into ISO format
  - Use ONLY for parsing user's date/time input
  - Call once per date input
  - Stop using once date is confirmed by user
  
- **`DateAndSlotFinderAgent`** - Find available slots for a date
  - Use for ALL slot availability queries
  - Use in Stage 2 validation before booking
  - Use when answering interruptible queries about availability
  - Use when rescheduling to verify new slot availability

### Direct Tool Calls (Use These Tools):
- `get_current_date()` - Returns current date
- `check_treatment_type()` - Returns list of available treatments

**Always use explicit named parameters** as defined in tool signatures.
    """,
    sub_agents=[date_and_slot_finder_agent, appointment_crud_agent],
    tools = [
        FunctionTool(func=get_current_date),
        AgentTool(agent=corrector_agent),
        # AgentTool(agent=find_slot_agent),
        FunctionTool(func=check_treatment_type),
        # FunctionTool(func=return_available_slots),
        # FunctionTool(func=check_availability),
        # FunctionTool(func=insert_appointment),
        # FunctionTool(func=delete_appointment),
        # FunctionTool(func=move_appointment)
    ]
)

