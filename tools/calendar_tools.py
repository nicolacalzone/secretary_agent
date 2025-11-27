from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.adk.tools.tool_context import ToolContext
import os.path
import datetime
import time
from zoneinfo import ZoneInfo
import subprocess


# read/write ops
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def is_it_holiday(date: str) -> bool:
    """Check if the given date is a holiday (weekend) using Google Calendar API.
    
    Args:
        date (str): Date in ISO format (YYYY-MM-DD) to check.
    Returns:
        bool: True if the date is a holiday (Saturday or Sunday), False otherwise.
    """
    dt = datetime.datetime.fromisoformat(date)
    # Check if it is Christmas, New Year, or weekend
    if dt.month == 12 and dt.day in [8, 24, 25, 26]:  #
        return True
    if dt.month == 1 and dt.day == 1:  #
        return True
    if dt.weekday() >= 5:  # Saturday or Sunday
        return True
    return False

def get_local_timezone():
    """Get the local timezone string for Google Calendar API."""
    try:
        # Try to get system timezone using timedatectl (Linux)
        result = subprocess.run(['timedatectl', 'show', '--value', '-p', 'Timezone'], 
                              capture_output=True, text=True, timeout=1)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except:
        pass
    
    # Fallback: use a common European timezone based on UTC offset
    utc_offset = -time.timezone if not time.daylight else -time.altzone
    hours = utc_offset // 3600
    
    # Map common offsets to timezone names
    timezone_map = {
        0: 'Europe/London',
        1: 'Europe/Rome',  # UTC+1
        2: 'Europe/Athens',
        -5: 'America/New_York',
        -8: 'America/Los_Angeles',
    }
    
    return timezone_map.get(hours, 'Europe/Rome')  # Default to Europe/Rome

def is_it_in_work_hours(date: str, time: str) -> bool:
    """Check if the given date and time fall within work hours (9 AM to 5 PM, Mon-Fri, non-holidays).
    
    Args:
        date (str): Date in ISO format (YYYY-MM-DD)
        time (str): Time in HH:MM format (24-hour) or just HH
    
    Returns:
        bool: True if within work hours and not a holiday, False otherwise
    """
    # Handle time format - add :00 if just hours provided
    if ':' not in time:
        time = f"{time}:00"
    
    # Check if it's a holiday first
    if is_it_holiday(date):
        return False
    
    # Create timezone-aware datetime in Europe/Rome timezone
    rome_tz = ZoneInfo('Europe/Rome')
    dt = datetime.datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=rome_tz)
    
    # Check if weekday (Mon-Fri)
    if dt.weekday() >= 5:
        return False
    # Check if time is within 9 AM to 5 PM (inclusive of 4 PM hour, exclusive of 5 PM)
    if dt.hour < 9 or dt.hour >= 17:
        return False
    return True

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

def parse_date_expression(expression: str) -> dict:
    """Parse natural language date expressions into ISO format dates.
    
    Handles relative dates (tomorrow, next Tuesday, in 3 days) and absolute dates.
    
    Args:
        expression (str): Natural language date expression like:
            - "tomorrow"
            - "next Tuesday"
            - "next week"
            - "in 3 days"
            - "December 5"
            - "2025-12-05"
    
    Returns:
        dict: Dictionary with parsed date information:
            - status (str): 'success' or 'error'
            - date (str): ISO format date (YYYY-MM-DD) if successful
            - day_name (str): Day of week name (e.g., "Monday")
            - message (str): Description or error message
    
    Examples:
        >>> parse_date_expression("tomorrow")
        {'status': 'success', 'date': '2025-11-28', 'day_name': 'Thursday', 'message': 'Tomorrow is Thursday, November 28, 2025'}
        
        >>> parse_date_expression("next tuesday")
        {'status': 'success', 'date': '2025-12-03', 'day_name': 'Tuesday', 'message': 'Next Tuesday is December 03, 2025'}
    """
    try:
        now = datetime.datetime.now()
        expression_lower = expression.lower().strip()
        
        # Remove common time indicators to extract just the date part
        # Handle patterns like "tomorrow at 10:00", "next Tuesday at 3pm", etc.
        time_separators = [' at ', ' @', ',']
        for separator in time_separators:
            if separator in expression_lower:
                expression_lower = expression_lower.split(separator)[0].strip()
                break
        
        # Handle "today"
        if expression_lower == "today":
            return {
                'status': 'success',
                'date': now.strftime('%Y-%m-%d'),
                'day_name': now.strftime('%A'),
                'message': f"Today is {now.strftime('%A, %B %d, %Y')}"
            }
        
        # Handle "tomorrow"
        if expression_lower == "tomorrow":
            tomorrow = now + datetime.timedelta(days=1)
            return {
                'status': 'success',
                'date': tomorrow.strftime('%Y-%m-%d'),
                'day_name': tomorrow.strftime('%A'),
                'message': f"Tomorrow is {tomorrow.strftime('%A, %B %d, %Y')}"
            }
        
        # Handle "day after tomorrow"
        if expression_lower in ["day after tomorrow", "overmorrow"]:
            day_after = now + datetime.timedelta(days=2)
            return {
                'status': 'success',
                'date': day_after.strftime('%Y-%m-%d'),
                'day_name': day_after.strftime('%A'),
                'message': f"Day after tomorrow is {day_after.strftime('%A, %B %d, %Y')}"
            }
        
        # Handle "next week"
        if expression_lower == "next week":
            next_week = now + datetime.timedelta(days=7)
            return {
                'status': 'success',
                'date': next_week.strftime('%Y-%m-%d'),
                'day_name': next_week.strftime('%A'),
                'message': f"Next week (same day) is {next_week.strftime('%A, %B %d, %Y')}"
            }
        
        # Handle "in X days"
        if expression_lower.startswith("in ") and "day" in expression_lower:
            try:
                parts = expression_lower.split()
                days_idx = next(i for i, word in enumerate(parts) if "day" in word)
                num_days = int(parts[days_idx - 1])
                target_date = now + datetime.timedelta(days=num_days)
                return {
                    'status': 'success',
                    'date': target_date.strftime('%Y-%m-%d'),
                    'day_name': target_date.strftime('%A'),
                    'message': f"In {num_days} days is {target_date.strftime('%A, %B %d, %Y')}"
                }
            except (ValueError, StopIteration):
                pass
        
        # Handle "next [weekday]" or just "[weekday]"
        weekdays = {
            'monday': 0, 'mon': 0,
            'tuesday': 1, 'tue': 1,
            'wednesday': 2, 'wed': 2,
            'thursday': 3, 'thu': 3,
            'friday': 4, 'fri': 4,
            'saturday': 5, 'sat': 5,
            'sunday': 6, 'sun': 6
        }
        
        for day_name, day_num in weekdays.items():
            if day_name in expression_lower:
                current_weekday = now.weekday()
                
                # Calculate days until target weekday
                if "next" in expression_lower:
                    # "next Tuesday" means the Tuesday in the next week
                    days_ahead = day_num - current_weekday
                    if days_ahead <= 0:
                        days_ahead += 7
                    # Always go to next week for "next [weekday]"
                    if days_ahead < 7:
                        days_ahead += 7
                else:
                    # Just "Tuesday" means the upcoming Tuesday (could be today if it's Tuesday)
                    days_ahead = day_num - current_weekday
                    if days_ahead < 0:
                        days_ahead += 7
                
                target_date = now + datetime.timedelta(days=days_ahead)
                return {
                    'status': 'success',
                    'date': target_date.strftime('%Y-%m-%d'),
                    'day_name': target_date.strftime('%A'),
                    'message': f"{'Next ' if 'next' in expression_lower else ''}{target_date.strftime('%A')} is {target_date.strftime('%B %d, %Y')}"
                }
        
        # Handle ISO format dates (YYYY-MM-DD)
        if len(expression_lower) == 10 and expression_lower.count('-') == 2:
            try:
                parsed_date = datetime.datetime.strptime(expression, '%Y-%m-%d')
                return {
                    'status': 'success',
                    'date': parsed_date.strftime('%Y-%m-%d'),
                    'day_name': parsed_date.strftime('%A'),
                    'message': f"{parsed_date.strftime('%A, %B %d, %Y')}"
                }
            except ValueError:
                pass
        
        # Handle numeric dates with spaces or slashes (e.g., "28 11 2025", "28/11/2025", "11-28-2025")
        numeric_date_formats = [
            '%d %m %Y',     # 28 11 2025
            '%d/%m/%Y',     # 28/11/2025
            '%d-%m-%Y',     # 28-11-2025
            '%m/%d/%Y',     # 11/28/2025 (US format)
            '%m-%d-%Y',     # 11-28-2025 (US format)
            '%Y %m %d',     # 2025 11 28
            '%Y/%m/%d',     # 2025/11/28
        ]
        
        for fmt in numeric_date_formats:
            try:
                parsed_date = datetime.datetime.strptime(expression_lower.strip(), fmt)
                return {
                    'status': 'success',
                    'date': parsed_date.strftime('%Y-%m-%d'),
                    'day_name': parsed_date.strftime('%A'),
                    'message': f"{parsed_date.strftime('%A, %B %d, %Y')}"
                }
            except ValueError:
                continue
        
        # Handle month names (e.g., "December 5", "Dec 5", "28 november 2025")
        month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                      'july', 'august', 'september', 'october', 'november', 'december',
                      'jan', 'feb', 'mar', 'apr', 'may', 'jun',
                      'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
        
        for month in month_names:
            if month in expression_lower:
                try:
                    # Try to parse various date formats
                    for fmt in [
                        '%B %d',           # December 5
                        '%b %d',           # Dec 5
                        '%B %d, %Y',       # December 5, 2025
                        '%b %d, %Y',       # Dec 5, 2025
                        '%d %B %Y',        # 28 November 2025
                        '%d %b %Y',        # 28 Nov 2025
                        '%d %B',           # 28 November
                        '%d %b',           # 28 Nov
                    ]:
                        try:
                            parsed_date = datetime.datetime.strptime(expression, fmt)
                            # If year not specified, use current year or next year if date has passed
                            if parsed_date.year == 1900:  # Default year from strptime
                                parsed_date = parsed_date.replace(year=now.year)
                                # If date has passed, use next year
                                if parsed_date < now:
                                    parsed_date = parsed_date.replace(year=now.year + 1)
                            
                            return {
                                'status': 'success',
                                'date': parsed_date.strftime('%Y-%m-%d'),
                                'day_name': parsed_date.strftime('%A'),
                                'message': f"{parsed_date.strftime('%A, %B %d, %Y')}"
                            }
                        except ValueError:
                            continue
                except:
                    pass
        
        # If we couldn't parse it, return error
        return {
            'status': 'error',
            'message': f"Could not parse date expression: '{expression}'. Please use expressions like 'tomorrow', 'next Tuesday', 'December 5', or ISO format 'YYYY-MM-DD'"
        }
    
    except Exception as e:
        return {
            'status': 'error',
            'message': f"Error parsing date: {str(e)}"
        }

def find_next_available_slot(date: str, time: str, max_attempts: int = 10) -> dict:
    """Find the next available time slot starting from the given date/time.
    
    Searches forward in 1-hour increments to find a free slot. Stops after max_attempts.
    
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
        local_tz = ZoneInfo('Europe/Rome')
        current_datetime = datetime.datetime.fromisoformat(f"{date}T{time}:00").replace(tzinfo=local_tz)
        
        for attempt in range(max_attempts):
            # Check this slot
            slot_start = current_datetime + datetime.timedelta(hours=attempt)
            slot_end = slot_start + datetime.timedelta(hours=1)
            
            # Query calendar for conflicts
            events_result = service.events().list(
                calendarId='primary',
                timeMin=slot_start.isoformat(),
                timeMax=slot_end.isoformat(),
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
    
    # First, validate work hours and holidays
    if not is_it_in_work_hours(date, time):
        return {
            'status': 'rejected',
            'is_available': False,
            'requested_date': date,
            'requested_time': time,
            'message': 'The requested time is outside business hours (9 AM - 5 PM, Monday-Friday) or falls on a holiday. Please choose a time during business hours.'
        }
    
    try:
        service = get_calendar_service()
        
        # Create time range for the requested slot (1 hour duration) with local timezone
        local_tz = ZoneInfo('Europe/Rome')
        start_datetime = datetime.datetime.fromisoformat(f"{date}T{time}:00").replace(tzinfo=local_tz)
        end_datetime = start_datetime + datetime.timedelta(hours=1)
        
        # Query calendar for events in this time range
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime.isoformat(),
            timeMax=end_datetime.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # SCENARIO 2: Slot is occupied - PAUSE and ask for approval of alternative time
        if events:
            # Find the next truly available slot
            next_slot = find_next_available_slot(date, time, max_attempts=10)
            
            if next_slot['status'] == 'rejected':
                # Couldn't find an available slot
                return {
                    'status': 'rejected',
                    'is_available': False,
                    'requested_date': date,
                    'requested_time': time,
                    'message': 'Time slot is occupied. No alternative slots available in the next 10 hours.'
                }
            
            alternative_date = next_slot['available_date']
            alternative_time = next_slot['available_time']
            
            # Request user confirmation for alternative time
            tool_context.request_confirmation(
                hint=f"⚠️ The time slot {time} on {date} is occupied. Would you like to book {alternative_date} at {alternative_time} instead?",
                payload={
                    'original_date': date,
                    'original_time': time,
                    'alternative_date': alternative_date,
                    'alternative_time': alternative_time
                }
            )
            
            return {
                'status': 'pending',
                'is_available': False,
                'requested_date': date,
                'requested_time': time,
                'alternative_date': alternative_date,
                'alternative_time': alternative_time,
                'message': f'Time slot is occupied. Would you like to book {alternative_date} at {alternative_time} instead?'
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

def insert_appointment(full_name: str, email: str, phone: str, date: str, time: str, tool_context: ToolContext = None) -> dict:
    """Insert a new appointment into Google Calendar.
    
    IMPORTANT: This function will ONLY insert if the slot is available.
    This function performs a final availability check before insertion.

    Args:
        full_name (str): Full name of the person booking the appointment
        email (str): Email address of the person booking the appointment
        phone (str): Phone number of the person booking the appointment
        date (str): Date of the appointment
        time (str): Time of the appointment
        tool_context (ToolContext): Context to track if availability was checked

    Returns:
        dict: Dictionary with appointment status.
    """
    # First, validate work hours and holidays
    if not is_it_in_work_hours(date, time):
        return {
            'status': 'rejected',
            'message': f'ERROR: Cannot book - the time {time} on {date} is outside business hours (9 AM - 5 PM, Monday-Friday) or falls on a holiday.'
        }
    
    try:
        service = get_calendar_service()
        
        # CRITICAL: Final availability check before inserting
        local_tz = ZoneInfo('Europe/Rome')
        start_datetime_obj = datetime.datetime.fromisoformat(f"{date}T{time}:00").replace(tzinfo=local_tz)
        end_datetime_obj = start_datetime_obj + datetime.timedelta(hours=1)
        
        # Check for conflicts
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime_obj.isoformat(),
            timeMax=end_datetime_obj.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if events:
            # Slot is occupied! Cannot proceed with booking
            # Find next available slot and return error with suggestion
            next_slot = find_next_available_slot(date, time, max_attempts=10)
            
            if next_slot['status'] == 'approved':
                alt_date = next_slot['available_date']
                alt_time = next_slot['available_time']
                return {
                    'status': 'rejected',
                    'message': f'ERROR: Cannot book - the slot on {date} at {time} is already occupied. The next available slot is {alt_date} at {alt_time}. Please use that time instead.'
                }
            else:
                return {
                    'status': 'rejected',
                    'message': f'ERROR: Cannot book - the slot on {date} at {time} is already occupied and no alternative slots are available in the next 10 hours.'
                }
        
        # Slot is free, proceed with booking
        local_tz = get_local_timezone()
        start_datetime = f"{date}T{time}:00"
        end_time = datetime.datetime.fromisoformat(start_datetime) + datetime.timedelta(hours=1)
        end_datetime = end_time.isoformat()
        
        event = {
            'summary': f'Appointment with {full_name}',
            'description': f'Phone: {phone}',
            'start': {
                'dateTime': start_datetime,
                'timeZone': local_tz,
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': local_tz,
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
            
            email_matches = email and any(att.get('email') == email for att in attendees)
            phone_matches = phone and phone in description
            
            # If both email and phone provided, both must match for identity verification
            if email and phone:
                if email_matches and phone_matches:
                    event_summary = event.get('summary')
                    event_id = event['id']
                    service.events().delete(calendarId='primary', eventId=event_id).execute()
                    return {
                        'status': 'approved',
                        'order_id': event_id,
                        'event_name': event_summary,
                        'message': f"Appointment '{event_summary}' successfully cancelled (verified with email and phone)"
                    }
            # If only email provided, check email
            elif email and email_matches:
                event_summary = event.get('summary')
                event_id = event['id']
                service.events().delete(calendarId='primary', eventId=event_id).execute()
                return {
                    'status': 'approved',
                    'order_id': event_id,
                    'event_name': event_summary,
                    'message': f"Appointment '{event_summary}' successfully cancelled"
                }
            # If only phone provided, check phone
            elif phone and phone_matches:
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

def move_appointment(email: str = None, phone: str = None, new_date: str = None, new_time: str = None, tool_context: ToolContext = None) -> dict:
    """Move an existing appointment to a new date/time in Google Calendar.
    
    Checks if the new time slot is available before rescheduling.
    If occupied, pauses and asks user to approve an alternative time.

    Args:
        email (str, optional): Email address to search for in appointment attendees
        phone (str, optional): Phone number to search for in appointment descriptions
        new_date (str): New date for the appointment
        new_time (str): New time for the appointment
        tool_context (ToolContext): ADK context for long-running operations
    
    Returns:
        dict: Dictionary with rescheduling status.
    """
    # -----------------------------------------------------------------------------------------------
    # SCENARIO 3: RESUME - User has responded to alternative time suggestion
    # -----------------------------------------------------------------------------------------------
    if tool_context and tool_context.tool_confirmation:
        if tool_context.tool_confirmation.confirmed:
            # User approved alternative time - extract from payload
            payload = tool_context.tool_confirmation.payload
            new_date = payload.get('alternative_date', new_date)
            new_time = payload.get('alternative_time')
            email = payload.get('email')
            phone = payload.get('phone')
            # Continue with rescheduling below
        else:
            # User rejected alternative time
            return {
                'status': 'rejected',
                'message': 'User declined the alternative time slot for rescheduling'
            }
    
    # -----------------------------------------------------------------------------------------------
    # SCENARIO 1 & 2: FIRST CALL - Check availability and reschedule
    # -----------------------------------------------------------------------------------------------
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
            
            email_matches = email and any(att.get('email') == email for att in attendees)
            phone_matches = phone and phone in description
            
            # If both email and phone provided, both must match for identity verification
            match_found = False
            if email and phone:
                match_found = email_matches and phone_matches
            elif email:
                match_found = email_matches
            elif phone:
                match_found = phone_matches
            
            if match_found:
                # Store old date for response
                old_start = event['start'].get('dateTime', event['start'].get('date'))
                old_date = old_start.split('T')[0] if 'T' in old_start else old_start
                old_time = old_start.split('T')[1][:5] if 'T' in old_start else '00:00'
                
                event_summary = event.get('summary')
                event_id = event['id']
                
                # CRITICAL: Check if new time slot is available before moving
                # First validate work hours
                if not is_it_in_work_hours(new_date, new_time):
                    return {
                        'status': 'rejected',
                        'message': f'Cannot reschedule - the time {new_time} on {new_date} is outside business hours (9 AM - 5 PM, Monday-Friday) or falls on a holiday.'
                    }
                
                # Check for conflicts in the new time slot (excluding current event)
                local_tz = ZoneInfo('Europe/Rome')
                start_datetime_obj = datetime.datetime.fromisoformat(f"{new_date}T{new_time}:00").replace(tzinfo=local_tz)
                end_datetime_obj = start_datetime_obj + datetime.timedelta(hours=1)
                
                conflicts_result = service.events().list(
                    calendarId='primary',
                    timeMin=start_datetime_obj.isoformat(),
                    timeMax=end_datetime_obj.isoformat(),
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                conflicting_events = conflicts_result.get('items', [])
                # Filter out the current event being moved
                conflicting_events = [e for e in conflicting_events if e['id'] != event_id]
                
                if conflicting_events:
                    # New slot is occupied! Cannot proceed
                    next_slot = find_next_available_slot(new_date, new_time, max_attempts=10)
                    
                    # Only pause for user confirmation if we're NOT already in a confirmation flow
                    if tool_context and not tool_context.tool_confirmation:
                        if next_slot['status'] == 'approved':
                            alt_date = next_slot['available_date']
                            alt_time = next_slot['available_time']
                            
                            # Request user confirmation for alternative time
                            tool_context.request_confirmation(
                                hint=f"⚠️ The requested time slot {new_time} on {new_date} is occupied. Would you like to reschedule to {alt_date} at {alt_time} instead?",
                                payload={
                                    'email': email,
                                    'phone': phone,
                                    'original_date': new_date,
                                    'original_time': new_time,
                                    'alternative_date': alt_date,
                                    'alternative_time': alt_time
                                }
                            )
                            
                            return {
                                'status': 'pending',
                                'message': f'The slot {new_time} on {new_date} is occupied. Alternative: {alt_date} at {alt_time}. Awaiting user confirmation.'
                            }
                    
                    # If no alternative or can't pause, reject
                    if next_slot['status'] == 'approved':
                        alt_date = next_slot['available_date']
                        alt_time = next_slot['available_time']
                        return {
                            'status': 'rejected',
                            'message': f'Cannot reschedule - the slot {new_time} on {new_date} is occupied. Next available: {alt_date} at {alt_time}.'
                        }
                    else:
                        return {
                            'status': 'rejected',
                            'message': f'Cannot reschedule - the slot {new_time} on {new_date} is occupied and no alternatives available.'
                        }
                
                # New slot is available - proceed with move
                local_tz = get_local_timezone()
                start_datetime = f"{new_date}T{new_time}:00"
                end_time = datetime.datetime.fromisoformat(start_datetime) + datetime.timedelta(hours=1)
                end_datetime = end_time.isoformat()
                
                event['start'] = {
                    'dateTime': start_datetime,
                    'timeZone': local_tz,
                }
                event['end'] = {
                    'dateTime': end_datetime,
                    'timeZone': local_tz,
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
                    'message': f"Appointment '{event_summary}' successfully rescheduled from {old_date} at {old_time} to {new_date} at {new_time}"
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
