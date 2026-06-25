import logging
import os
import re
from telegram import Update
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

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Scans messages for Instagram/TikTok links and downloads/shares the video.
        """
        if not update.message or not update.message.text:
            return

        text = update.message.text
        match = SOCIAL_LINK_PATTERN.search(text)
        if not match:
            return

        url = match.group(0)
        logger.info(f"Detected social media link: {url} from user {update.effective_user.id}")

        # Send a status message
        status_msg = await update.message.reply_text("🔄 Downloading video...")

        # Run downloading in an executor or async loop (yt-dlp is blocking, so we run it in a thread executor)
        loop = context.application.loop
        success, raw_path, message = await loop.run_in_executor(
            None, self.downloader.download, url
        )

        if not success or not raw_path:
            logger.error(f"Download failed for {url}: {message}")
            await status_msg.edit_text(f"❌ {message}")
            return

        # Optimize video for mobile streaming
        await status_msg.edit_text("⚙️ Optimizing video for mobile...")
        final_path, optimized = await loop.run_in_executor(
            None, self.downloader.optimize_video, raw_path
        )

        # Upload video
        await status_msg.edit_text("📤 Uploading to Telegram...")
        try:
            with open(final_path, 'rb') as video_file:
                # Send the video file
                await update.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="Here is your video! 🎥",
                    write_timeout=120
                )
            
            # Clean up message status
            await status_msg.delete()
        except Exception as e:
            logger.exception(f"Failed to upload video to telegram: {e}")
            await status_msg.edit_text(f"❌ Failed to upload video: {str(e)}")
        finally:
            # Always clean up temp file
            if final_path and os.path.exists(final_path):
                try:
                    os.remove(final_path)
                    logger.info(f"Cleaned up temp video file: {final_path}")
                except OSError as e:
                    logger.error(f"Error removing temp file {final_path}: {e}")
