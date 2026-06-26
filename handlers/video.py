import asyncio
import logging
import os
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from services.downloader import DownloaderService

logger = logging.getLogger(__name__)

# Compile regexes for TikTok and Instagram links
SOCIAL_LINK_PATTERN = re.compile(
    r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv|share/[^/]+)/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/video/[0-9]+'
    r'|https?://(?:vm|vt|v)\.tiktok\.com/[A-Za-z0-9]+)',
    re.IGNORECASE
)

class VideoHandler:
    def __init__(self, downloader_service: DownloaderService):
        self.downloader = downloader_service
        # Cache to store the URL mapped to the message ID that contains the inline button
        self.url_cache = {}

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Scans messages for Instagram/TikTok links and replies with a download button.
        """
        if not update.message or not update.message.text:
            return

        text = update.message.text
        match = SOCIAL_LINK_PATTERN.search(text)
        if not match:
            return

        url = match.group(0)
        logger.info(f"Detected social media link: {url} from user {update.effective_user.id}")

        # Send a reply with an inline keyboard
        keyboard = [
            [InlineKeyboardButton("🎬 Download Video", callback_data="download_video")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        reply_msg = await update.message.reply_text(
            "Video link detected! Click the button below to download.",
            reply_markup=reply_markup
        )

        # Store the URL using the reply message's ID as the key
        self.url_cache[str(reply_msg.message_id)] = url

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the inline button click to trigger the actual video download.
        """
        query = update.callback_query
        await query.answer()

        if query.data != "download_video":
            return

        msg_id = str(query.message.message_id)
        url = self.url_cache.get(msg_id)

        if not url:
            await query.edit_message_text("❌ Link expired or not found. Please send the link again.")
            return

        # Start download process
        await query.edit_message_text("🔄 Downloading video...")

        # Run downloading in an executor or async loop (yt-dlp is blocking, so we run it in a thread executor)
        loop = asyncio.get_running_loop()
        try:
            success, raw_path, message = await asyncio.wait_for(
                loop.run_in_executor(None, self.downloader.download, url),
                timeout=120  # 2 minutes timeout for download
            )
        except asyncio.TimeoutError:
            logger.error(f"Download timed out for {url}")
            await query.edit_message_text("❌ Download timed out after 2 minutes.")
            return

        if not success or not raw_path:
            logger.error(f"Download failed for {url}: {message}")
            await query.edit_message_text(f"❌ {message}")
            return

        # Optimize video for mobile streaming
        await query.edit_message_text("⚙️ Optimizing video for mobile...")
        try:
            final_path, optimized = await asyncio.wait_for(
                loop.run_in_executor(None, self.downloader.optimize_video, raw_path),
                timeout=180  # 3 minutes optimization timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Optimization timed out for {raw_path}")
            if raw_path and os.path.exists(raw_path):
                try:
                    os.remove(raw_path)
                except OSError:
                    pass
            await query.edit_message_text("❌ Video optimization timed out.")
            return

        # Upload video
        await query.edit_message_text("📤 Uploading to Telegram...")
        try:
            with open(final_path, 'rb') as video_file:
                # Send the video file
                await query.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="Here is your video! 🎥",
                    write_timeout=120
                )
            
            # Clean up message status
            await query.message.delete()
        except Exception as e:
            logger.exception(f"Failed to upload video to telegram: {e}")
            await query.edit_message_text(f"❌ Failed to upload video: {str(e)}")
        finally:
            # Always clean up temp file
            if final_path and os.path.exists(final_path):
                try:
                    os.remove(final_path)
                    logger.info(f"Cleaned up temp video file: {final_path}")
                except OSError as e:
                    logger.error(f"Error removing temp file {final_path}: {e}")
