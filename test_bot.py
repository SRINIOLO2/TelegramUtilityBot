import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, CallbackQuery, Message, User
from handlers.video import VideoHandler
from services.downloader import DownloaderService

async def main():
    downloader = DownloaderService("temp")
    handler = VideoHandler(downloader)

    update = MagicMock(spec=Update)
    query = AsyncMock(spec=CallbackQuery)
    query.data = "download_video"
    query.message = MagicMock(spec=Message)
    query.message.message_id = 123
    query.from_user = MagicMock(spec=User)
    query.from_user.id = 1
    
    update.callback_query = query
    
    # Pre-populate cache
    handler.url_cache["123"] = "https://www.tiktok.com/@zachking/video/6768504823336815877"
    
    context = MagicMock()
    
    print("Testing button_callback...")
    await handler.button_callback(update, context)
    print("Finished.")

asyncio.run(main())
