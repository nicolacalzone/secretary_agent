"""
Telegram Agent - Handles incoming messages and bridges to GENERAL_AGENT
"""
import logging
import uuid
from typing import Any, Dict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google.genai import types

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
        
        logger.info(f"User {user_id}: {user_message}")
        
        try:
            # Send typing indicator to show bot is working
            await update.message.chat.send_action("typing")
            
            # Get or create session for this user
            if user_id not in self.user_sessions:
                session_id = f"telegram_user_{user_id}_{uuid.uuid4().hex[:8]}"
                await self.session_service.create_session(
                    app_name="booking_coordinator",
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
                    
                    # Extract and send response
                    response_text = self._extract_text_from_events(events)
                    if response_text:
                        await update.message.reply_text(response_text)
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
            query_content = types.Content(role="user", parts=[types.Part(text=user_message)])
            events = []
            
            try:
                async for event in self.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=query_content
                ):
                    events.append(event)
            except TypeError as te:
                logger.error(f"TypeError during agent execution: {te}", exc_info=True)
                # Check if we got any events before the error
                if events:
                    # Try to extract response from events we did get
                    response_text = self._extract_text_from_events(events)
                    if response_text and response_text != "Processing...":
                        await update.message.reply_text(response_text)
                        return
                # If no useful events, show error
                await update.message.reply_text(
                    "😓 I encountered a technical issue. Please try rephrasing your request."
                )
                return
            except Exception as e:
                logger.error(f"Unexpected error during agent execution: {e}", exc_info=True)
                # Check if we got any events before the error
                if events:
                    response_text = self._extract_text_from_events(events)
                    if response_text and response_text != "Processing...":
                        await update.message.reply_text(response_text)
                        return
                await update.message.reply_text(
                    "😓 Sorry, I encountered an error processing your request."
                )
                return
            
            # Check if agent is requesting approval
            approval_info = self._check_for_approval(events)
            
            if approval_info:
                # Store approval info for this user
                self.user_sessions[user_id]['pending_approval'] = approval_info
                
                # Extract and send response (agent should have informed user about alternative)
                response_text = self._extract_text_from_events(events)
                if response_text:
                    await update.message.reply_text(response_text + "\n\n⏸️ Please reply 'yes' or 'no'.")
                else:
                    await update.message.reply_text(
                        "The requested time slot is occupied. An alternative has been suggested.\n\n"
                        "⏸️ Please reply 'yes' to approve or 'no' to decline."
                    )
            else:
                # No approval needed - normal response
                logger.info(f"Agent response events: {events}")
                response_text = self._extract_text_from_events(events)
                if response_text:
                    await update.message.reply_text(response_text)
                else:
                    await update.message.reply_text("I'm processing your request...")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
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
    
    def _extract_text_from_events(self, events):
        """Extract text responses from events"""
        response_text = ""
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text
        return response_text.strip() if response_text else "Processing..."
    
    def run(self):
        """Start the Telegram bot (blocking)"""
        logger.info("🤖 Starting Telegram bot...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def start_async(self):
        """Start the Telegram bot (async)"""
        logger.info("🤖 Starting Telegram bot (async mode)...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    async def stop_async(self):
        """Stop the Telegram bot (async)"""
        logger.info("🛑 Stopping Telegram bot...")
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
