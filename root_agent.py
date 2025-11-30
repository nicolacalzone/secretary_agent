"""
Telegram Bot Entry Point
Run this to start the Telegram interface for the booking system
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging removed per user request


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
    from telegram_agent import TelegramAgent
    from agents.general_agent import general_runner, session_service
    
    # Create Telegram agent as root_agent(uses implicit caching via Gemini 2.5)
    root_agent = TelegramAgent(
        token=telegram_token,
        general_runner=general_runner,
        session_service=session_service
    )
    
    # Start bot
    # Startup messages removed
    
    try:
        root_agent.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        raise


if __name__ == "__main__":
    main()
