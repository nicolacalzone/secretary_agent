"""
Telegram Agent - Handles incoming messages and bridges to GENERAL_AGENT
"""
import logging
from typing import Any, Dict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logger = logging.getLogger(__name__)


class TelegramAgent:
    """
    Telegram interface agent that:
    - Receives messages from Telegram users
    - Routes them to GENERAL_AGENT
    - Sends responses back to Telegram
    - Manages user sessions
    """
    
    def __init__(self, token: str, general_agent, session_manager):
        """
        Initialize Telegram bot
        
        Args:
            token: Telegram bot token from @BotFather
            general_agent: The GENERAL_AGENT instance to route messages to
            session_manager: SessionManager instance for persisting state
        """
        self.token = token
        self.general_agent = general_agent
        self.session_manager = session_manager
        self.app = Application.builder().token(token).build()
        
        # Register command and message handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("cancel", self.cancel_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - Initialize new session"""
        user_id = str(update.effective_user.id)
        session_id = f"tg_{user_id}"
        
        # Initialize session in database
        self.session_manager.create_session(session_id, user_id)
        
        await update.message.reply_text(
            "👋 *Welcome to our appointment booking system!*\n\n"
            "I can help you:\n"
            "• 📅 Book a new appointment\n"
            "• 🔄 Reschedule existing appointments\n"
            "• ❌ Cancel appointments\n"
            "• 📋 Check your bookings\n\n"
            "Just tell me what you need!\n\n"
            "_Commands:_\n"
            "/status - Check current booking progress\n"
            "/cancel - Cancel current booking\n"
            "/help - Show this message",
            parse_mode="Markdown"
        )
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command - Clear current session"""
        user_id = str(update.effective_user.id)
        session_id = f"tg_{user_id}"
        
        self.session_manager.clear_session(session_id)
        
        await update.message.reply_text(
            "❌ Current booking cancelled.\n\n"
            "You can start a new booking anytime by just sending me a message!"
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - Show current booking progress"""
        user_id = str(update.effective_user.id)
        session_id = f"tg_{user_id}"
        
        state = self.session_manager.get_session(session_id)
        
        if not state or not state.get("booking"):
            await update.message.reply_text(
                "📭 No active booking in progress.\n\n"
                "Start a new booking by telling me what you need!"
            )
            return
        
        booking = state["booking"]
        status_text = "📋 *Current Booking Status:*\n\n"
        status_text += f"Service: `{booking.get('service', 'Not set')}`\n"
        status_text += f"Date: `{booking.get('date', 'Not set')}`\n"
        status_text += f"Time: `{booking.get('time', 'Not set')}`\n"
        status_text += f"Name: `{booking.get('customer_name', 'Not set')}`\n"
        status_text += f"People: `{booking.get('number_of_people', 1)}`\n"
        status_text += f"Status: `{booking.get('status', 'pending')}`"
        
        await update.message.reply_text(status_text, parse_mode="Markdown")
    
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
            "/status - Check your current booking\n"
            "/cancel - Cancel current booking\n"
            "/help - Show this message",
            parse_mode="Markdown"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages - Route to GENERAL_AGENT"""
        user_id = str(update.effective_user.id)
        session_id = f"tg_{user_id}"
        user_message = update.message.text
        
        logger.info(f"User {user_id}: {user_message}")
        
        try:
            # Load session state from database
            session_state = self.session_manager.get_session(session_id)
            if not session_state:
                # Auto-create session if doesn't exist
                session_state = self.session_manager.create_session(session_id, user_id)
            
            # Send typing indicator to show bot is working
            await update.message.chat.send_action("typing")
            
            # Call GENERAL_AGENT with message and session context
            # The exact invocation depends on how your ADK agent is structured
            response = await self.general_agent.process(
                message=user_message,
                session_id=session_id,
                user_id=user_id,
                memory=session_state
            )
            
            # Save updated session state to database
            if response.get("memory"):
                self.session_manager.save_session(session_id, response["memory"])
            
            # Send response back to user
            response_text = response.get("message", "I'm processing your request...")
            await update.message.reply_text(
                response_text,
                parse_mode="Markdown" if response.get("use_markdown", True) else None
            )
            
        except Exception as e:
            logger.error(f"Error processing message from user {user_id}: {e}", exc_info=True)
            await update.message.reply_text(
                "😓 Sorry, I encountered an error processing your request.\n\n"
                "Please try again or use /cancel to start over."
            )
    
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
