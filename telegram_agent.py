"""
Telegram Agent - Handles incoming messages and bridges to GENERAL_AGENT
"""
import logging
import uuid
import re
from typing import Any, Dict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google.genai import types
import datetime

logger = logging.getLogger(__name__)

class TelegramAgent:
    """
    Telegram interface agent that:
    - Receives messages from Telegram users
    - Routes them to GENERAL_AGENT
    - Sends responses back to Telegram
    """
    
    def __init__(self, token: str, general_runner, session_service):
        """
        Initialize Telegram bot
        
        Args:
            token: Telegram bot token from @BotFather
            general_runner: The Runner instance to execute agent
            session_service: Session service for managing conversation state
        """
        self.token = token
        self.runner = general_runner
        self.session_service = session_service
        self.app = Application.builder().token(token).build()
        
        # Simple in-memory user data cache (implicit caching handles the rest)
        self.user_data_cache: Dict[str, Dict[str, str]] = {}
        
        # Store session info per user: {user_id: {'session_id': str, 'pending_approval': dict}}
        self.user_sessions = {}
        
        # Register command and message handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("cancel", self.cancel_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "👋 *Welcome to our appointment booking system!*\n\n"
            "I can help you:\n"
            "• 📅 Book a new appointment\n"
            "• 🔄 Reschedule existing appointments\n"
            "• ❌ Cancel appointments\n"
            "• 📋 Check your bookings\n\n"
            "Just tell me what you need!\n\n"
            "_Commands:_\n"
            "/help - Show this message",
            parse_mode="Markdown"
        )
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command"""
        await update.message.reply_text(
            "You can start a new booking anytime by just sending me a message!"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command - Show help message"""
        await update.message.reply_text(
            "🤖 *Appointment Booking Assistant*\n\n"
            "*How to use:*\n"
            "Just chat with me naturally! Tell me what you need.\n\n"
            "*Examples:*\n"
            "• \"I need a haircut on Friday at 3pm\"\n"
            "• \"Book a dental cleaning next week\"\n"
            "• \"Reschedule my appointment to tomorrow\"\n\n"
            "*Commands:*\n"
            "/start - Start over\n"
            "/cancel - Cancel current booking\n"
            "/help - Show this message",
            parse_mode="Markdown"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages - Route to GENERAL_AGENT with LRO support"""
        user_message = update.message.text
        user_id = str(update.effective_user.id)
        
        
        # Extract and store user information (implicit caching will optimize reuse)
        extracted_info = self._extract_user_info(user_message)
        if extracted_info:
            if user_id not in self.user_data_cache:
                self.user_data_cache[user_id] = {}
            self.user_data_cache[user_id].update(extracted_info)
            

        # Cache the year: current year or next year if the mentioned date passed
        inferred_year = self._infer_year_from_message(user_message)
        if user_id not in self.user_data_cache:
            self.user_data_cache[user_id] = {}
        # Only set if not already cached, to keep consistency within a flow
        if 'year' not in self.user_data_cache[user_id] and inferred_year:
            self.user_data_cache[user_id]['year'] = str(inferred_year)

        try:
            # Send typing indicator to show bot is working
            await update.message.chat.send_action("typing")
            
            # Get or create session for this user
            if user_id not in self.user_sessions:
                session_id = f"telegram_user_{user_id}_{uuid.uuid4().hex[:8]}"
                await self.session_service.create_session(
                    app_name="agents",
                    user_id=user_id,
                    session_id=session_id
                )
                self.user_sessions[user_id] = {
                    'session_id': session_id,
                    'pending_approval': None
                }
            
            session_id = self.user_sessions[user_id]['session_id']
            pending_approval = self.user_sessions[user_id]['pending_approval']
            
            # -----------------------------------------------------------------------------------------------
            # SCENARIO 1: User is responding to a pending approval (yes/no)
            # -----------------------------------------------------------------------------------------------
            if pending_approval:
                # Check if user said yes or no
                user_response_lower = user_message.lower().strip()
                approved = user_response_lower in ['yes', 'y', 'ok', 'approve', 'sure', 'yeah', 'yep']
                rejected = user_response_lower in ['no', 'n', 'reject', 'nope', 'cancel']
                
                if approved or rejected:
                    # Create approval response
                    confirmation_response = types.FunctionResponse(
                        id=pending_approval['approval_id'],
                        name="adk_request_confirmation",
                        response={"confirmed": approved}
                    )
                    
                    approval_message = types.Content(
                        role="user",
                        parts=[types.Part(function_response=confirmation_response)]
                    )
                    
                    # Resume the agent with approval decision
                    events = []
                    async for event in self.runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=approval_message,
                        invocation_id=pending_approval['invocation_id']
                    ):
                        events.append(event)
                    
                    # Clear pending approval
                    self.user_sessions[user_id]['pending_approval'] = None
                    
                    # Extract and send responses (may be multiple messages)
                    response_texts = self._extract_text_messages_from_events(events)
                    if response_texts:
                        for text in response_texts:
                            await update.message.reply_text(text)
                    else:
                        await update.message.reply_text("Booking processed!")
                    
                    return
                else:
                    # User didn't say yes/no clearly
                    await update.message.reply_text(
                        "Please respond with 'yes' to approve the alternative time or 'no' to decline."
                    )
                    return
            
            # -----------------------------------------------------------------------------------------------
            # SCENARIO 2: Normal message (no pending approval)
            # -----------------------------------------------------------------------------------------------
            
            # Prepend user data to message if available (triggers implicit caching)
            message_to_send = user_message
            if user_id in self.user_data_cache:
                user_data = self.user_data_cache[user_id]
                context_parts = []
                if user_data.get('full_name'):
                    context_parts.append(f"Name: {user_data['full_name']}")
                if user_data.get('email'):
                    context_parts.append(f"Email: {user_data['email']}")
                if user_data.get('phone'):
                    context_parts.append(f"Phone: {user_data['phone']}")
                
                if context_parts:
                    cached_context = "[User Info from previous messages: " + ", ".join(context_parts) + "]\n\n"
                    message_to_send = cached_context + user_message
            
            query_content = types.Content(role="user", parts=[types.Part(text=message_to_send)])
            events = []
            
            try:
                async for event in self.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=query_content
                ):
                    events.append(event)
            except TypeError as te:
                # Check if we got any events before the error
                if events:
                    # Try to extract response from events we did get
                    response_text = self._extract_text_from_events(events)
                    if response_text and response_text != "Processing...":
                        await update.message.reply_text(response_text)
                        return
                
                # Log the full error for debugging
                
                # If no useful events, show error with more context
                await update.message.reply_text(
                    f"😓 I encountered a technical issue. Please try rephrasing your request.\n\n"
                    f"Debug: {str(te)[:200]}"
                )
                return
            except Exception as e:
                # Check if we got any events before the error
                if events:
                    response_text = self._extract_text_from_events(events)
                    if response_text and response_text != "Processing...":
                        await update.message.reply_text(response_text)
                        return
                
                # Show more helpful error message
                await update.message.reply_text(
                    f"😓 Sorry, I encountered an error: {str(e)[:200]}\n\n"
                    "Please try again or contact support."
                )
                return
            
            # Check if agent is requesting approval
            approval_info = self._check_for_approval(events)
            
            if approval_info:
                # Store approval info for this user
                self.user_sessions[user_id]['pending_approval'] = approval_info
                
                # Extract and send responses (may be multiple messages)
                response_texts = self._extract_text_messages_from_events(events)
                if response_texts:
                    for text in response_texts:
                        await update.message.reply_text(text)
                    # Add approval prompt after last message
                    await update.message.reply_text("⏸️ Please reply 'yes' or 'no'.")
                else:
                    await update.message.reply_text(
                        "The requested time slot is occupied. An alternative has been suggested.\n\n"
                        "⏸️ Please reply 'yes' to approve or 'no' to decline."
                    )
            else:
                # No approval needed - normal response
                logger.info(f"Agent response events: {events}")
                response_texts = self._extract_text_messages_from_events(events)
                if response_texts:
                    for text in response_texts:
                        await update.message.reply_text(text)
                else:
                    await update.message.reply_text("I'm processing your request...")
            
        except Exception as e:
            await update.message.reply_text(
                "😓 Sorry, I encountered an error processing your request.\n\n"
                "Please try again."
            )
    
    def _check_for_approval(self, events):
        """Check if events contain an approval request (adk_request_confirmation)"""
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if (
                        part.function_call
                        and part.function_call.name == "adk_request_confirmation"
                    ):
                        return {
                            "approval_id": part.function_call.id,
                            "invocation_id": event.invocation_id,
                        }
        return None
    
    def _extract_user_info(self, message: str) -> Dict[str, Any]:
        """Extract user information from message using regex patterns."""
        extracted = {}
        
        # Email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, message)
        if emails:
            extracted['email'] = emails[0]
        
        # Phone pattern (various formats including long digit strings)
        phone_patterns = [
            r'\b(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',  # (123) 456-7890 or 123-456-7890
            r'\b\d{10,15}\b',  # 10-15 consecutive digits
        ]
        for pattern in phone_patterns:
            phones = re.findall(pattern, message)
            if phones:
                extracted['phone'] = phones[0].strip()
                break
        
        # Try to detect name - match 2-4 capitalized words after trigger phrases
        name_patterns = [
            (r'(?:my name is|i am|i\'m|this is|name:)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})(?=\s+(?:and|for|to|on|at|,|$))', re.IGNORECASE),
            (r'(?:^|\n)([A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+)(?:\s+and\s+|\s*,|\s*$)', 0),
        ]
        for pattern, flags in name_patterns:
            match = re.search(pattern, message, flags)
            if match:
                extracted['full_name'] = match.group(1).strip()
                break
        
        return extracted

    def _infer_year_from_message(self, message: str) -> int | None:
        """Infer the intended year from the user's message.

        Rule:
        - Default to current year.
        - If a month/day is present and that date in the current year has already passed today,
          choose next year.
        - If the message explicitly contains a 4-digit year, return that year.
        """
        now = datetime.datetime.now()
        # Explicit year in message
        year_match = re.search(r"\b(20\d{2})\b", message)
        if year_match:
            try:
                return int(year_match.group(1))
            except ValueError:
                pass

        # Try to extract month/day without year
        month_map = {
            'jan': 1, 'january': 1,
            'feb': 2, 'february': 2,
            'mar': 3, 'march': 3,
            'apr': 4, 'april': 4,
            'may': 5,
            'jun': 6, 'june': 6,
            'jul': 7, 'july': 7,
            'aug': 8, 'august': 8,
            'sep': 9, 'september': 9,
            'oct': 10, 'october': 10,
            'nov': 11, 'november': 11,
            'dec': 12, 'december': 12,
        }

        text = message.lower()
        # Patterns: "Dec 2", "December 2", "2 Dec", "2 December"
        # Month name first
        mm1 = re.search(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})\b", text)
        # Day first
        mm2 = re.search(r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", text)
        # Numeric DD MM or MM DD (without year)
        mm3 = re.search(r"\b(\d{1,2})[\s/.-](\d{1,2})(?![\s/.-]\d{2,4})\b", text)

        target_date = None
        try:
            if mm1:
                month = month_map[mm1.group(1)[:3]]
                day = int(mm1.group(2))
                target_date = datetime.datetime(now.year, month, day)
            elif mm2:
                day = int(mm2.group(1))
                month = month_map[mm2.group(2)[:3]]
                target_date = datetime.datetime(now.year, month, day)
            elif mm3:
                d1 = int(mm3.group(1))
                d2 = int(mm3.group(2))
                # Decide if format is DD MM or MM DD based on plausible ranges
                if d1 <= 12 and d2 <= 12:
                    # Ambiguous; assume first is month if both <=12
                    month, day = d1, d2
                elif d1 <= 12 and d2 <= 31:
                    month, day = d1, d2
                elif d1 <= 31 and d2 <= 12:
                    day, month = d1, d2
                else:
                    month, day = None, None
                if month and day:
                    target_date = datetime.datetime(now.year, month, day)
        except ValueError:
            target_date = None

        if target_date:
            # If the target date this year has already passed relative to today, use next year
            if target_date.date() < now.date():
                return now.year + 1
            return now.year

        # Fallback: just current year
        return now.year
    
    def _extract_text_messages_from_events(self, events):
        """Extract text responses from events as separate messages.
        
        Returns a list of text messages, one for each text part found.
        This allows the bot to send multiple messages if the agent generates multiple responses.
        """
        messages = []
        
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    # 1) Plain text parts from the agent
                    if part.text:
                        # Clean the text
                        text = part.text.strip()
                        # Remove cached context that agent might echo
                        text = re.sub(r'\[User Info from previous messages:[^\]]*\]\s*', '', text)
                        if text:  # Only add non-empty messages
                            messages.append(text)
                    # 2) Function responses from tools (surface useful 'message' fields)
                    elif getattr(part, 'function_response', None):
                        try:
                            func_name = part.function_response.name or ""
                            payload = part.function_response.response or {}
                            # Common tool response pattern with 'message'
                            if isinstance(payload, dict):
                                # Prefer a 'message' field if present
                                if 'message' in payload and isinstance(payload['message'], str):
                                    msg = payload['message'].strip()
                                    if msg:
                                        messages.append(msg)
                                else:
                                    # Provide minimal summaries for known tool responses
                                    if 'available_slots' in payload and 'date' in payload:
                                        slots = payload.get('available_slots') or []
                                        date = payload.get('date')
                                        messages.append(f"Available slots on {date}: {', '.join(slots) if slots else 'none'}")
                                    elif 'treatments' in payload and isinstance(payload['treatments'], list):
                                        treatments = payload['treatments']
                                        messages.append(f"We offer {len(treatments)} treatments: {', '.join(treatments)}")
                                    elif 'status' in payload and 'requested_date' in payload and 'requested_time' in payload:
                                        # check_availability minimal echo
                                        status = payload.get('status')
                                        if status == 'approved':
                                            messages.append("The requested time slot is available.")
                                        elif status == 'pending':
                                            alt_d = payload.get('alternative_date')
                                            alt_t = payload.get('alternative_time')
                                            if alt_d and alt_t:
                                                messages.append(f"The requested time is occupied. Alternative suggested: {alt_d} at {alt_t}.")
                        except Exception:
                            # Silently ignore malformed function responses
                            pass
        
        # If no text messages but we have events with function calls
        if not messages and events:
            for event in events:
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call:
                            # We had function calls but no text response
                            return ["I'm working on your request..."]
        
        return messages if messages else ["Processing..."]
    
    def _extract_text_from_events(self, events):
        """Extract text responses from events (legacy method - combines all text into one).
        
        Kept for backward compatibility but _extract_text_messages_from_events is preferred.
        """
        messages = self._extract_text_messages_from_events(events)
        return " ".join(messages) if messages else "Processing..."
    
    def run(self):
        """Start the Telegram bot (blocking)"""
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def start_async(self):
        """Start the Telegram bot (async)"""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    async def stop_async(self):
        """Stop the Telegram bot (async)"""
        
        # Clear in-memory cache
        self.user_data_cache.clear()
        
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
