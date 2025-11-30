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

# 1. Specialist Agent for Date/Time Parsing and Validation
corrector_agent = LlmAgent(
    name="CorrectorAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""
    You are an agent that identifies and corrects date and time inputs.
    If the user provides relative dates ("today", "tomorrow", "next Monday"), call get_current_date(), use the output to understand which date user wants in his query in "YYYY-MM-DD" format. Then send the date you identified to parse_date_expression().
    
    If the user provides only the date like "24th", then assume it as the next occurrence of that date in the future. call get_current_date() to understand the current date context. use current date to determine the correct month and year the user is referring to. 
    Remember to always return the date you determined in ISO format (YYYY-MM-DD).
    
    Parse date expressions into ISO format (YYYY-MM-DD). Then use parse_date_expression() function and normalize time to 24-hour format.

    Process:
    1. Call get_current_date() to establish reference date.
    2. Correct the users date input to ISO format with relevant year/month/day. 
        Remember that "24th" means the next occurrence of the 24th in the future.
        If the date has already passed this month, move to next month.
        Important: Use the output of get_current_date(), understand the date user refers to in his query and change it into YYYY-MM-DD format before giving it to parse_date_expression().
    2. Call parse_date_expression() with corrected user's date input.
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
    description="Agent to handle date parsing and slot finding. Return the response in clear natural language regarding date and available slots.",
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

---

## BOOKING WORKFLOW (3 Stages - Must Complete in Order)

### Stage 1: INFORMATION COLLECTION
Gather all required fields:
- **Date**: If ambiguous (e.g., "tomorrow", "the 24th", "next Friday"):
  1. Call `get_current_date()` first
  2. Delegate to `date_and_slot_finder_agent` (it will parse the date AND find slots)
  3. Confirm the parsed date with user
  4. Do NOT call date parsing again unless user requests a change
- **Time**: Ask if not provided (default: 09:00 if user agrees)
- **Treatment**: Default to "General Consultation" if not mentioned
- **Contact**: Full name, email, phone number

### Stage 2: VALIDATION OF SLOTS
**Slot Availability Check:**
- The slots were already retrieved by `date_and_slot_finder_agent` in Stage 1
- Verify the requested time is in the available slots
- If not available → ask for alternative time or date
- If new date needed → delegate to `date_and_slot_finder_agent` again

### Stage 3: VALIDATION OF DETAILS
Before proceeding with booking, verify ALL five required fields are present:
✓ Date (ISO format)
✓ Time (HH:MM format)
✓ Full name
✓ Email
✓ Phone

**Slot Availability Check:**
1. Delegate to `date_and_slot_finder_agent` with the requested date
2. If slots available at requested time → proceed to Stage 3
3. If no slots available → inform user and ask for alternative date
4. Return to Stage 1 if new date needed

**STRICT GUARD**: If ANY field is missing, respond ONLY with:
"To proceed with booking, I still need: [comma-separated missing fields]"

Do NOT call any appointment tools until all five fields are confirmed.

### Stage 4: EXECUTION
Call tools in this exact sequence:
1. `check_availability(date, time)` 
2. If available → `insert_appointment(full_name, email, phone, date, time, treatment)`
3. Respond with explicit confirmation including:
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

**How to Handle:**
1. **Immediately** answer the query:
   - **Available slots / availability queries** → Delegate to `date_and_slot_finder_agent`
   - **Treatment list** → Call `check_treatment_type()` directly
   - **Current date** → Call `get_current_date()` directly

2. After answering, if booking is incomplete:
   - Acknowledge the answer you just provided
   - Gently prompt for the next missing field: "Great! Now, to complete your booking, may I have your [missing field]?"

**Important**: Never block these queries behind missing contact information.

---

## OTHER OPERATIONS

### Cancel Appointment
- Tool: `delete_appointment(email OR phone)`
- Only ONE identifier required (email OR phone)
- Ask for confirmation before executing

### Reschedule Appointment
- Tool: `move_appointment(email OR phone, new_date, new_time)`
- If new date is ambiguous, use CorrectorAgent to parse
- Use `date_and_slot_finder_agent` to verify new time slot availability before executing

### Identifier Matching Rules
- **Email**: Normalized to lowercase, trimmed
- **Phone**: Digits only (leading '+' preserved)
- **Lookup**: Either email OR phone is sufficient
- Legacy events without metadata fall back to attendee email or description phone digits

---

## TOOL CALLING RULES

### Agent Delegation (Use These Agents):
- **`CorrectorAgent`** - Parse ambiguous dates/times into ISO format
  - Use ONLY for parsing user's date/time input
  - Call once per date input
  - Stop using once date is confirmed by user
  
- **`date_and_slot_finder_agent`** - Find available slots for a date
  - Use for ALL slot availability queries
  - Use in Stage 2 validation before booking
  - Use when answering interruptible queries about availability
  - Use when rescheduling to verify new slot availability

### Direct Tool Calls (Use These Tools):
- `get_current_date()` - Returns current date
- `check_treatment_type()` - Returns list of available treatments
- `check_availability(date, time)` - Checks if specific slot is available (use in Stage 3)
- `insert_appointment(full_name, email, phone, date, time, treatment)` - Creates booking
- `delete_appointment(email OR phone)` - Cancels booking
- `move_appointment(email OR phone, new_date, new_time)` - Reschedules booking

**Always use explicit named parameters** as defined in tool signatures.

---

## Example Flow

**User**: "I need an appointment for the 24th"

**Agent**:
1. Call `get_current_date()` → Nov 30, 2025
2. Delegate to `CorrectorAgent("the 24th")` → "2025-12-24"
3. Respond: "I understand you want Tuesday, December 24, 2025. Is that correct?"
4. [User confirms]
5. "Great! What time works best for you?"
6. [User provides time]
7. Delegate to `date_and_slot_finder_agent("2025-12-24")` to verify slots available
8. "Perfect, that time is available. May I have your full name?"
9. [Continue collecting email, phone]
10. Once all fields collected → `check_availability(date, time)` → `insert_appointment(...)`
11. "✓ Your appointment is confirmed for December 24, 2025 at [time]. [Calendar link]"

---

## Example: Interruptible Query

**User**: "What slots are available tomorrow?"

**Agent**:
1. Call `get_current_date()` → Nov 30, 2025
2. Delegate to `CorrectorAgent("tomorrow")` → "2025-12-01"
3. Delegate to `date_and_slot_finder_agent("2025-12-01")`
4. Respond: "Here are the available slots for December 1, 2025: [list slots from agent response]"
5. If booking in progress: "Which time would you prefer?"

---

## Example: Reschedule with Verification

**User**: "Can I reschedule my appointment to next Wednesday at 2pm?"

**Agent**:
1. Call `get_current_date()` → Nov 30, 2025
2. Delegate to `CorrectorAgent("next Wednesday")` → "2025-12-03"
3. Delegate to `date_and_slot_finder_agent("2025-12-03")` to check availability
4. If 14:00 slot available → "Yes, 2pm is available on December 3rd. May I have your email or phone to locate your appointment?"
5. [User provides identifier]
6. Call `move_appointment(email, "2025-12-03", "14:00")`
7. "✓ Your appointment has been rescheduled to Wednesday, December 3, 2025 at 14:00.
    """,
    sub_agents=[date_and_slot_finder_agent, appointment_crud_agent],
    tools = [
        FunctionTool(func=get_current_date),
        # AgentTool(agent=corrector_agent),
        # AgentTool(agent=find_slot_agent),
        FunctionTool(func=check_treatment_type),
        # FunctionTool(func=return_available_slots),
        FunctionTool(func=check_availability),
        FunctionTool(func=insert_appointment),
        FunctionTool(func=delete_appointment),
        FunctionTool(func=move_appointment)
    ]
)

