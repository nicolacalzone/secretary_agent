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
    check_availability,
    find_next_available_slot
)

# 1. Specialist Agent for Validation
corrector_agent = LlmAgent(
    name="CorrectorAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You are a date/time validator and formatter.
    
    IMPORTANT: Always call the get_current_date tool first to get today's date before processing any date/time inputs.
    
    Your task is to convert any date/time input into ISO format (YYYY-MM-DD for dates, HH:MM for times).
    
    Date Conversion Rules:
    - If only a day number is provided (e.g., "6th", "15th", "on the 23rd"):
      * Compare the day with today's date (from get_current_date tool)
      * If that day has already passed in the current month, use that day in the NEXT month
      * If that day hasn't passed yet in the current month, use that day in the CURRENT month
      * Always use the current year (or next year if needed)
    
    - If day and month are provided (e.g., "15th December", "March 3rd"):
      * Use the current year
      * If the date has already passed this year, use next year
    
    - If full date is provided (e.g., "2025-12-06", "December 6th 2026"):
      * Use the exact date provided
    
    - For relative dates (e.g., "tomorrow", "next Monday", "in 3 days"):
      * Calculate the exact date based on today's date from get_current_date
    
    Time Conversion Rules:
    - Convert to 24-hour format (HH:MM)
    - Handle AM/PM notation (e.g., "3:30 PM" → "15:30")
    - If only hour is given (e.g., "3pm", "15"), assume ":00" minutes
    - Default to "09:00" if no time is specified
    
    IMPORTANT: You must always respond with text containing the validated date and time.
    
    Examples (assuming today is 2025-11-26):
    - Input: "on 6th" → Output: "Validated date: 2025-12-06"
    - Input: "on 30th" → Output: "Validated date: 2025-11-30"
    - Input: "March 15" → Output: "Validated date: 2026-03-15"
    - Input: "3:30 PM" → Output: "Validated time: 15:30"
    - Input: "tomorrow at 2pm" → Output: "Validated date: 2025-11-27, time: 14:00"
    
    Always respond with the validated ISO format date and time in clear text.
    """,
    tools=[
        FunctionTool(func=get_current_date)
    ]
)

# 2. Specialist Agent for Finding Available Slots
find_slot_agent = LlmAgent(
    name="FindAvailableSlotAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You find the next available time slot in the calendar.
    
    Your task:
    1. Call find_next_available_slot with the starting date and time
    2. The function will search forward in 1-hour increments (up to 10 slots by default)
    3. ALWAYS return a clear text response with the results
    
    IMPORTANT: You must always respond with text. Never return an empty response.
    
    Example responses:
    - "✅ The next available slot is on 2025-12-06 at 15:00 (checked 2 slots)"
    - "❌ No available slots found in the next 10 hours after the requested time"
    """,
    tools=[
        FunctionTool(func=find_next_available_slot)
    ]
)

# 3. Specialist Agent for Availability Checking
availability_agent = LlmAgent(
    name="AvailabilityAgent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You check if a time slot is available in the calendar.
    
    Your task:
    1. Call check_availability tool with the provided date and time
    2. Check the response status:
       - If status is 'approved' and is_available is True: The slot is free, proceed with booking
       - If status is 'pending': The slot is occupied and an alternative time has been suggested - inform the user they need to respond
       - If status is 'rejected': Either the user declined the alternative or there was an error
    3. ALWAYS return a clear text response describing the status
    
    IMPORTANT: You must always respond with text. Never return an empty response.
    
    Example responses:
    - "✅ The time slot 2025-12-06 at 14:00 is available and ready for booking."
    - "⏸️ The time slot 2025-12-06 at 14:00 is occupied. Alternative time suggested: 15:00. Please respond yes or no."
    - "✅ Alternative time slot 15:00 has been approved and is ready for booking."
    - "❌ The slot is not available and no alternatives were found."
    """,
    tools=[
        FunctionTool(func=check_availability)
    ]
)

# 4. Specialist Agent for Appointment Operations
appointment_crud_agent = LlmAgent(
    name="AppointmentCRUD",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    instruction="""You handle appointment database operations.
        If the user asks for Scheduling (INSERT) an appointment:
            1. Ask for: full_name, email, phone, date, time
            2. Proceed to call the insert_appointment tool.
        
        If the user asks for Cancelling (DELETE) an appointment:
            1. Ask for: email OR phone to identify the appointment
            2. Proceed to call the delete_appointment tool.

        If the user asks for Moving (MOVE) an appointment:
            1. Ask for: email OR phone to identify the appointment, new_date, new_time
            2. Proceed to call the move_appointment tool.
        
        After receiving the final result, provide a clear summary including:
            - Order status (approved/rejected)
            - date and time of the appointment (if applicable)
        
        Always validate that required fields are present before calling tools.
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
    instruction="""
    You are a Calendar coordinator.
    
    Workflow for BOOKING appointments:
    1. Use CorrectorAgent to validate and convert date/time formats to ISO format
    2. Use check_availability tool DIRECTLY to check if the time slot is available
       - If status='approved' and is_available=True: Proceed to booking
       - If status='pending': STOP and inform user an alternative has been suggested, they must respond yes/no
       - If status='rejected': Inform user the slot cannot be booked
    3. Once status='approved', use AppointmentCRUD to book the appointment
    4. Provide clear confirmation to the user with booking details
    
    Workflow for CANCELLING appointments:
    1. Use AppointmentCRUD directly to cancel
    
    Workflow for RESCHEDULING appointments:
    1. Use CorrectorAgent to validate new date/time
    2. Use check_availability to verify new slot
    3. If approved, use AppointmentCRUD to reschedule
    
    IMPORTANT: 
    - When check_availability returns status='pending', DO NOT proceed with booking
    - The user must respond yes/no to the alternative time first
    - Always provide clear text responses
    
    Keep your role focused on coordination.
    """,
    tools=[
        AgentTool(agent=corrector_agent),
        FunctionTool(func=check_availability),  # Use directly, not through agent
        AgentTool(agent=find_slot_agent),
        AgentTool(agent=appointment_crud_agent)
    ]
)


