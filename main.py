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
    CallbackQueryHandler,
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# Import handlers and services
from services.downloader import DownloaderService
from handlers.video import VideoHandler

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Load local environment variables
load_dotenv()


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Command /start: Welcomes the user.
    """
    await update.message.reply_text(
        "👋 *Welcome to MetaHaterBot!*\n\n"
        "📹 *Supported Platforms & Media*:\n"
        "• *Instagram* (Reels, Video Posts, Single Images & Photo Carousels)\n"
        "• *TikTok* (Videos & Photo Posts)\n"
        "• *YouTube* (Videos & Shorts — manual trigger)\n\n"
        "⚡ *How to use*:\n"
        "• *Bot DM / Groups*: Send any Instagram or TikTok link and tap *📥 Download* (prompt auto-hides after 45s if untouched).\n"
        "• *YouTube / Manual Download*: Reply `/dl` (or `@metahaterbot`) to any link, or send `/dl <link>`.\n"
        "• *1-on-1 Private Chats*: Type `@metahaterbot <link>` (or just `@metahaterbot ` to pick a recent link) and tap *📥 Download* to load the video/photo directly into your chat!\n\n"
        "Commands:\n"
        "• `/start` - Show this help message\n"
        "• `/dl <link>` - Manually trigger download for any Instagram, TikTok, or YouTube link",
        parse_mode="Markdown",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global error handler for logging transient network errors cleanly.
    """
    logger.warning(f"Update caused error: {context.error}")


def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not bot_token:
        logger.critical("TELEGRAM_BOT_TOKEN is missing from .env. Please set it. Exiting.")
        return

    # Initialize Services & Handlers
    downloader_service = DownloaderService("temp")
    video_handler = VideoHandler(downloader_service)

    # Configure resilient HTTPX requests to prevent stale keep-alive ConnectErrors
    api_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=120.0,
        pool_timeout=15.0,
    )
    polling_request = HTTPXRequest(
        connection_pool_size=4,
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=15.0,
    )

    # Initialize Bot Application
    app = (
        ApplicationBuilder()
        .token(bot_token)
        .request(api_request)
        .get_updates_request(polling_request)
        .build()
    )

    # Register Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler(["dl", "download"], video_handler.handle_message))

    # Register Inline Query Handler for 1-on-1 chats and groups
    app.add_handler(InlineQueryHandler(video_handler.handle_inline_query))

    # Register Text & Caption Message Handler for links in direct DMs / groups
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            video_handler.handle_message,
        )
    )

    # Register Callback Query Handler for inline buttons
    app.add_handler(CallbackQueryHandler(video_handler.button_callback))

    # Register Global Error Handler
    app.add_error_handler(error_handler)

    # Start the bot
    logger.info("Bot is starting... Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
