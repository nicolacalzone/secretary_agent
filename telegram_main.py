"""
Telegram Bot Entry Point
Run this to start the Telegram interface for the booking system
"""
import os
import logging
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for Telegram bot"""
    
    # Get Telegram bot token from environment
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is required.\n"
            "Get your token from @BotFather on Telegram and add it to .env file:\n"
            "TELEGRAM_BOT_TOKEN=your_token_here"
        )
    
    # Import dependencies (after env is loaded)
    from agents.telegram_agent import TelegramAgent
    from agents.general_agent import general_agent
    from memory.session_manager import SessionManager
    from db.mysql_client import MySQLClient
    
    # Initialize database and session manager
    logger.info("Initializing database connection...")
    db_client = MySQLClient()
    session_manager = SessionManager(db_client)
    
    # Create Telegram agent
    logger.info("Creating Telegram agent...")
    telegram_agent = TelegramAgent(
        token=telegram_token,
        general_agent=general_agent,
        session_manager=session_manager
    )
    
    # Start bot
    logger.info("=" * 60)
    logger.info("🤖 TELEGRAM BOOKING BOT STARTED")
    logger.info("=" * 60)
    logger.info("Bot is now listening for messages...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    try:
        telegram_agent.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down bot...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
