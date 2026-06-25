import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv

# Import handlers and services
from services.downloader import DownloaderService
from handlers.video import VideoHandler

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load local environment variables
load_dotenv()

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Command /start: Welcomes the user.
    """
    await update.message.reply_text(
        "👋 Welcome to your Video Downloader Bot!\n\n"
        "📹 *How to use*:\n"
        "Simply send or forward any Instagram Reel, Post, or TikTok video link to this chat, "
        "and I will download and send it back to you as an inline-playable video file optimized for mobile.\n\n"
        "Commands:\n"
        "• /start - Show this welcome message",
        parse_mode="Markdown"
    )

def main():
    # Fetch secrets from environment
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not bot_token:
        logger.critical("TELEGRAM_BOT_TOKEN is missing from .env. Please set it. Exiting.")
        return

    # Initialize Services & Handlers
    downloader_service = DownloaderService("temp")
    video_handler = VideoHandler(downloader_service)

    # Initialize Bot Application
    app = ApplicationBuilder().token(bot_token).build()

    # Register Commands
    app.add_handler(CommandHandler("start", start_cmd))

    # Register Text Message Handler for video links
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, video_handler.handle_message))

    # Start the bot
    logger.info("Bot is starting... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
