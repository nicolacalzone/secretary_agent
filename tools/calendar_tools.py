from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.adk.tools.tool_context import ToolContext
import os.path
import datetime


# Scopes needed for calendar read/write operations
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_calendar_service():
    """Get authenticated Google Calendar service."""
    creds = None
    
    # Get the directory where this file is located
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Build paths to credentials and token files
    credentials_path = os.path.join(current_dir, "..", "config", "credentials.json")
    token_path = os.path.join(current_dir, "..", "config", "token.json")
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    
    return build("calendar", "v3", credentials=creds)

def get_current_date() -> str:
    """Get the current date and time."""
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')} (ISO: {now.strftime('%Y-%m-%d')}). Current time is {now.strftime('%H:%M')}."

def find_next_available_slot(date: str, time: str, max_attempts: int = 10) -> dict:
    """Find the next available time slot starting from the given date/time.
    
    Searches forward in 1-hour increments to find a free slot.
    
    Args:
        date (str): Starting date in ISO format (YYYY-MM-DD)
        time (str): Starting time in HH:MM format (24-hour)
        max_attempts (int): Maximum number of slots to check (default: 10)
    
    Returns:
        dict: Dictionary with available slot info:
            - status (str): 'approved' if slot found, 'rejected' if none found
            - available_date (str): Date of available slot
            - available_time (str): Time of available slot
            - attempts_checked (int): Number of slots checked
            - message (str): Description
    """
    try:
        service = get_calendar_service()
        current_datetime = datetime.datetime.fromisoformat(f"{date}T{time}:00")
        
        for attempt in range(max_attempts):
            # Check this slot
            slot_start = current_datetime + datetime.timedelta(hours=attempt)
            slot_end = slot_start + datetime.timedelta(hours=1)
            
            # Query calendar for conflicts
            events_result = service.events().list(
                calendarId='primary',
                timeMin=slot_start.isoformat() + 'Z',
                timeMax=slot_end.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # If no conflicts, this slot is available
            if not events:
                return {
                    'status': 'approved',
                    'available_date': slot_start.strftime('%Y-%m-%d'),
                    'available_time': slot_start.strftime('%H:%M'),
                    'attempts_checked': attempt + 1,
                    'message': f'Found available slot at {slot_start.strftime("%Y-%m-%d %H:%M")} after checking {attempt + 1} slot(s)'
                }
        
        # No available slot found within max_attempts
        return {
            'status': 'rejected',
            'message': f'No available slot found after checking {max_attempts} time slots'
        }
    
    except HttpError as error:
        return {
            'status': 'rejected',
            'message': f'Error searching for available slots: {error}'
        }
    except Exception as e:
        return {
            'status': 'rejected',
            'message': f'Failed to find available slot: {str(e)}'
        }

def check_availability(date: str, time: str, tool_context: ToolContext) -> dict:
    """Check if a time slot is available in Google Calendar.
    
    Checks if the requested time slot (with 1-hour duration) conflicts with existing appointments.
    If the slot is occupied, pauses execution and asks user to approve an alternative time (+1 hour).
    
    Args:
        date (str): Date to check
        time (str): Start time to check
    
    Returns:
        dict: Dictionary with availability status.

        Examples:
            Available: {
                'status': 'approved',
                'is_available': True,
                'requested_date': '2025-12-06',
                'requested_time': '14:00',
            }
            
            Occupied (first call - pauses): {
                'status': 'pending',
                'is_available': False,
                'requested_date': '2025-12-06',
                'requested_time': '14:00',
            }
            
            Occupied (after user approval): {
                'status': 'approved',
                'is_available': True,
                'requested_date': '2025-12-06',
                'requested_time': '15:00',
            }
    """
    # -----------------------------------------------------------------------------------------------
    # SCENARIO 3: RESUME - User has responded to alternative time suggestion
    # -----------------------------------------------------------------------------------------------
    if tool_context.tool_confirmation:
        if tool_context.tool_confirmation.confirmed:
            # User approved alternative time - extract it from payload
            payload = tool_context.tool_confirmation.payload
            alternative_date = payload.get('alternative_date', date)
            alternative_time = payload.get('alternative_time')
            return {
                'status': 'approved',
                'is_available': True,
                'requested_date': alternative_date,
                'requested_time': alternative_time,
                'message': f'Alternative time slot approved: {alternative_date} at {alternative_time}'
            }
        else:
            # User rejected alternative time
            return {
                'status': 'rejected',
                'is_available': False,
                'requested_date': date,
                'requested_time': time,
                'message': 'User declined the alternative time slot'
            }
    
    # -----------------------------------------------------------------------------------------------
    # SCENARIO 1 & 2: FIRST CALL - Check availability
    # -----------------------------------------------------------------------------------------------
    try:
        service = get_calendar_service()
        
        # Create time range for the requested slot (1 hour duration)
        start_datetime = datetime.datetime.fromisoformat(f"{date}T{time}:00")
        end_datetime = start_datetime + datetime.timedelta(hours=1)
        
        # Query calendar for events in this time range
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime.isoformat() + 'Z',
            timeMax=end_datetime.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # SCENARIO 2: Slot is occupied - PAUSE and ask for approval of alternative time
        if events:
            conflicting_event = events[0].get('summary', 'Unknown event')
            
            # Find the next truly available slot
            next_slot = find_next_available_slot(date, time, max_attempts=10)
            
            if next_slot['status'] == 'rejected':
                # Couldn't find an available slot
                return {
                    'status': 'rejected',
                    'is_available': False,
                    'requested_date': date,
                    'requested_time': time,
                    'conflicting_event': conflicting_event,
                    'message': f'Time slot conflicts with: {conflicting_event}. No alternative slots available in the next 10 hours.'
                }
            
            alternative_date = next_slot['available_date']
            alternative_time = next_slot['available_time']
            
            # Request user confirmation for alternative time
            tool_context.request_confirmation(
                hint=f"⚠️ The time slot {time} on {date} is occupied by '{conflicting_event}'. Would you like to book {alternative_date} at {alternative_time} instead?",
                payload={
                    'original_date': date,
                    'original_time': time,
                    'alternative_date': alternative_date,
                    'alternative_time': alternative_time,
                    'conflicting_event': conflicting_event
                }
            )
            
            return {
                'status': 'pending',
                'is_available': False,
                'requested_date': date,
                'requested_time': time,
                'alternative_date': alternative_date,
                'alternative_time': alternative_time,
                'conflicting_event': conflicting_event,
                'message': f'Time slot conflicts with: {conflicting_event}. Would you like to book {alternative_date} at {alternative_time} instead?'
            }
        
        # SCENARIO 1: No conflicts - slot is available, auto-approve
        return {
            'status': 'approved',
            'is_available': True,
            'requested_date': date,
            'requested_time': time,
            'message': 'Time slot is available'
        }
    
    except HttpError as error:
        return {
            'status': 'rejected',
            'is_available': False,
            'message': f'An error occurred while checking availability: {error}'
        }
    except Exception as e:
        return {
            'status': 'rejected',
            'is_available': False,
            'message': f'Failed to check availability: {str(e)}'
        }

def insert_appointment(full_name: str, email: str, phone: str, date: str, time: str) -> dict:
    """Insert a new appointment into Google Calendar.

    Args:
        full_name (str): Full name of the person booking the appointment
        email (str): Email address of the person booking the appointment
        phone (str): Phone number of the person booking the appointment
        date (str): Date of the appointment
        time (str): Time of the appointment

    Returns:
        dict: Dictionary with appointment status.
    """
    try:
        service = get_calendar_service()
        
        # Combine date and time into ISO format
        start_datetime = f"{date}T{time}:00"
        # Assuming 1 hour duration for appointments
        end_time = datetime.datetime.fromisoformat(start_datetime) + datetime.timedelta(hours=1)
        end_datetime = end_time.isoformat()
        
        event = {
            'summary': f'Appointment with {full_name}',
            'description': f'Phone: {phone}',
            'start': {
                'dateTime': start_datetime,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': email},
            ],
        }
        
        event = service.events().insert(calendarId='primary', body=event).execute()
        return {
            'status': 'approved',
            'order_id': event.get('id'),
            'link': event.get('htmlLink'),
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'date': date,
            'time': time,
            'message': f'Appointment successfully booked for {full_name} on {date} at {time}'
        }
    
    except HttpError as error:
        return {
            'status': 'rejected',
            'message': f'An error occurred: {error}'
        }
    except Exception as e:
        return {
            'status': 'rejected',
            'message': f'Failed to create appointment: {str(e)}'
        }

def delete_appointment(email: str = None, phone: str = None) -> dict:
    """Searches for upcoming appointments matching the provided email or phone number,
    then deletes the first matching appointment found.
    
    Args:
        email (str, optional): Email address to search for in appointment attendees.
        phone (str, optional): Phone number to search for in appointment descriptions.
        

    Args:
        email (str, optional): Email address to search for in appointment attendees;
        phone (str, optional): Phone number to search for in appointment descriptions;
        new_date (str): New date for the appointment;
        new_time (str): New time for the appointment;
    
    Returns:
        dict: Dictionary with rescheduling status.
    """

    try:
        service = get_calendar_service()
        
        # Search for events matching the email or phone
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=100,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Find matching event
        for event in events:
            attendees = event.get('attendees', [])
            description = event.get('description', '')
            
            # Check if email matches any attendee
            if email and any(att.get('email') == email for att in attendees):
                event_summary = event.get('summary')
                event_id = event['id']
                service.events().delete(calendarId='primary', eventId=event_id).execute()
                return {
                    'status': 'approved',
                    'order_id': event_id,
                    'event_name': event_summary,
                    'message': f"Appointment '{event_summary}' successfully cancelled"
                }
            
            # Check if phone is in description
            if phone and phone in description:
                event_summary = event.get('summary')
                event_id = event['id']
                service.events().delete(calendarId='primary', eventId=event_id).execute()
                return {
                    'status': 'approved',
                    'order_id': event_id,
                    'event_name': event_summary,
                    'message': f"Appointment '{event_summary}' successfully cancelled"
                }
        
        return {
            'status': 'rejected',
            'message': 'No matching appointment found to cancel'
        }
    
    except HttpError as error:
        return {
            'status': 'rejected',
            'message': f'An error occurred: {error}'
        }
    except Exception as e:
        return {
            'status': 'rejected',
            'message': f'Failed to cancel appointment: {str(e)}'
        }

def move_appointment(email: str = None, phone: str = None, new_date: str = None, new_time: str = None) -> dict:
    """Move an existing appointment to a new date/time in Google Calendar.

    Args:
        email (str, optional): Email address to search for in appointment attendees;
        phone (str, optional): Phone number to search for in appointment descriptions;
        new_date (str): New date for the appointment;
        new_time (str): New time for the appointment;
    
    Returns:
        dict: Dictionary with rescheduling status.
    """
    try:
        service = get_calendar_service()
        
        # Search for events matching the email or phone
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=100,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Find matching event
        for event in events:
            attendees = event.get('attendees', [])
            description = event.get('description', '')
            
            match_found = False
            if email and any(att.get('email') == email for att in attendees):
                match_found = True
            elif phone and phone in description:
                match_found = True
            
            if match_found:
                # Store old date for response
                old_start = event['start'].get('dateTime', event['start'].get('date'))
                old_date = old_start.split('T')[0] if 'T' in old_start else old_start
                
                event_summary = event.get('summary')
                event_id = event['id']
                
                # Update the event with new date/time
                start_datetime = f"{new_date}T{new_time}:00"
                end_time = datetime.datetime.fromisoformat(start_datetime) + datetime.timedelta(hours=1)
                end_datetime = end_time.isoformat()
                
                event['start'] = {
                    'dateTime': start_datetime,
                    'timeZone': 'UTC',
                }
                event['end'] = {
                    'dateTime': end_datetime,
                    'timeZone': 'UTC',
                }
                
                updated_event = service.events().update(
                    calendarId='primary',
                    eventId=event_id,
                    body=event
                ).execute()
                
                return {
                    'status': 'approved',
                    'order_id': event_id,
                    'event_name': event_summary,
                    'old_date': old_date,
                    'new_date': new_date,
                    'new_time': new_time,
                    'message': f"Appointment '{event_summary}' successfully rescheduled to {new_date} at {new_time}"
                }
        
        return {
            'status': 'rejected',
            'message': 'No matching appointment found to reschedule'
        }
    
    except HttpError as error:
        return {
            'status': 'rejected',
            'message': f'An error occurred: {error}'
        }
    except Exception as e:
        return {
            'status': 'rejected',
            'message': f'Failed to reschedule appointment: {str(e)}'
        }
