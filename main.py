import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    InlineQueryHandler,
    CallbackQueryHandler
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
        "• Send or forward any Instagram Reel, Post, or TikTok video link to this chat.\n"
        "• In any other chat or group, type `@metahaterbot <link>` to use inline mode.\n"
        "• Click the download button to fetch the video.\n\n"
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

    # Register Inline Query Handler for 1-on-1 chats and groups
    app.add_handler(InlineQueryHandler(video_handler.handle_inline_query))

    # Register Text Message Handler for video links in direct DMs / groups
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, video_handler.handle_message))

    # Register Callback Query Handler for inline buttons
    app.add_handler(CallbackQueryHandler(video_handler.button_callback))

    # Start the bot
    logger.info("Bot is starting... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
