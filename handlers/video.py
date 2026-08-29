import asyncio
import hashlib
import logging
import os
import re
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes
from services.downloader import DownloaderService

logger = logging.getLogger(__name__)

# Compile regexes for TikTok and Instagram links
SOCIAL_LINK_PATTERN = re.compile(
    r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv|share/[^/]+)/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/video/[0-9]+'
    r'|https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9]+'
    r'|https?://(?:vm|vt|v)\.tiktok\.com/[A-Za-z0-9]+)',
    re.IGNORECASE
)

class VideoHandler:
    def __init__(self, downloader_service: DownloaderService):
        self.downloader = downloader_service
        # Cache to store the URL mapped to the message ID or callback query data
        self.url_cache = {}
        # Store recent links per user for quick inline access
        self.recent_user_links = {}
        
        # Concurrency protections
        self.global_semaphore = asyncio.Semaphore(3)
        self.user_locks = {}

    def get_user_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self.user_locks:
            self.user_locks[user_id] = asyncio.Lock()
        return self.user_locks[user_id]

    def save_user_link(self, user_id: int, url: str) -> None:
        if user_id not in self.recent_user_links:
            self.recent_user_links[user_id] = []
        if url in self.recent_user_links[user_id]:
            self.recent_user_links[user_id].remove(url)
        self.recent_user_links[user_id].insert(0, url)
        # Keep last 5 links
        self.recent_user_links[user_id] = self.recent_user_links[user_id][:5]

    async def handle_inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles inline queries so users can type @bot <link> or just @bot in any chat.
        """
        query = update.inline_query.query.strip()
        user_id = update.inline_query.from_user.id
        results = []

        # Case 1: User pasted a link in the inline query
        if query:
            match = SOCIAL_LINK_PATTERN.search(query)
            if match:
                url = match.group(0)
                self.save_user_link(user_id, url)
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                self.url_cache[url_hash] = url

                keyboard = [
                    [InlineKeyboardButton("🎬 Download & Send Video", callback_data=f"dl_{url_hash}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                results.append(
                    InlineQueryResultArticle(
                        id=url_hash,
                        title="🎬 Download Video",
                        description=f"Send download button for: {url[:45]}...",
                        input_message_content=InputTextMessageContent(
                            f"📹 *Video Link:*\n{url}\n\n_Click below to download directly to this chat._",
                            parse_mode="Markdown"
                        ),
                        reply_markup=reply_markup
                    )
                )

        # Case 2: User opened @bot with empty query -> show recent links!
        if not results and user_id in self.recent_user_links:
            for idx, url in enumerate(self.recent_user_links[user_id]):
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                self.url_cache[url_hash] = url
                keyboard = [
                    [InlineKeyboardButton("🎬 Download & Send Video", callback_data=f"dl_{url_hash}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                results.append(
                    InlineQueryResultArticle(
                        id=f"rec_{url_hash}_{idx}",
                        title=f"Recent Link #{idx+1}",
                        description=f"{url[:50]}...",
                        input_message_content=InputTextMessageContent(
                            f"📹 *Video Link:*\n{url}\n\n_Click below to download directly to this chat._",
                            parse_mode="Markdown"
                        ),
                        reply_markup=reply_markup
                    )
                )

        await update.inline_query.answer(results, cache_time=0, is_personal=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Scans messages for Instagram/TikTok links, or checks replied-to messages if user mentions the bot.
        """
        if not update.message:
            return

        text = update.message.text or update.message.caption or ""
        match = SOCIAL_LINK_PATTERN.search(text)

        # If no link in the message itself, check if user replied to a message containing a link
        if not match and update.message.reply_to_message:
            replied = update.message.reply_to_message
            replied_text = replied.text or replied.caption or ""
            match = SOCIAL_LINK_PATTERN.search(replied_text)

        if not match:
            return

        url = match.group(0)
        logger.info(f"Detected social media link: {url} from user {update.effective_user.id}")

        if update.effective_user:
            self.save_user_link(update.effective_user.id, url)

        # Create a short hash for callback data
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        self.url_cache[url_hash] = url

        # Send a reply with an inline keyboard for video download
        keyboard = [
            [InlineKeyboardButton("🎬 Download Video", callback_data=f"dl_{url_hash}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        reply_msg = await update.message.reply_text(
            "Video link detected! Click the button below to download.",
            reply_markup=reply_markup
        )

        # Also store with message ID as backup
        self.url_cache[str(reply_msg.message_id)] = url

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles the inline button click to trigger the actual video download.
        """
        query = update.callback_query
        data = query.data or ""

        url = None
        if data.startswith("dl_"):
            url_hash = data[3:]
            url = self.url_cache.get(url_hash)
        elif data == "download_video" and query.message:
            msg_id = str(query.message.message_id)
            url = self.url_cache.get(msg_id)

        user_id = query.from_user.id

        if not url:
            await query.answer("❌ Link expired or not found. Please paste the link again.", show_alert=True)
            return

        user_lock = self.get_user_lock(user_id)
        
        if user_lock.locked():
            await query.answer("⚠️ You already have a video processing! Please wait.", show_alert=True)
            return
            
        await query.answer()

        async with user_lock:
            # Check global semaphore
            if self.global_semaphore.locked():
                if query.inline_message_id:
                    await context.bot.edit_message_text(
                        "⏳ Queued (Server busy, please wait)...",
                        inline_message_id=query.inline_message_id
                    )
                elif query.message:
                    await query.edit_message_text("⏳ Queued (Server busy, please wait)...")
            
            async with self.global_semaphore:
                # Start download process
                if query.inline_message_id:
                    await context.bot.edit_message_text(
                        "🔄 Downloading video...",
                        inline_message_id=query.inline_message_id
                    )
                elif query.message:
                    await query.edit_message_text("🔄 Downloading video...")

                loop = asyncio.get_running_loop()
                try:
                    success, raw_path, message = await asyncio.wait_for(
                        loop.run_in_executor(None, self.downloader.download, url),
                        timeout=120  # 2 minutes timeout for download
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Download timed out for {url}")
                    if query.inline_message_id:
                        await context.bot.edit_message_text("❌ Download timed out after 2 minutes.", inline_message_id=query.inline_message_id)
                    elif query.message:
                        await query.edit_message_text("❌ Download timed out after 2 minutes.")
                    return

                if not success or not raw_path:
                    logger.error(f"Download failed for {url}: {message}")
                    if query.inline_message_id:
                        await context.bot.edit_message_text(f"❌ {message}", inline_message_id=query.inline_message_id)
                    elif query.message:
                        await query.edit_message_text(f"❌ {message}")
                    return

                # Optimize video for mobile streaming
                if query.inline_message_id:
                    await context.bot.edit_message_text("⚙️ Optimizing video for mobile...", inline_message_id=query.inline_message_id)
                elif query.message:
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
                    if query.inline_message_id:
                        await context.bot.edit_message_text("❌ Video optimization timed out.", inline_message_id=query.inline_message_id)
                    elif query.message:
                        await query.edit_message_text("❌ Video optimization timed out.")
                    return

                # Upload video
                if query.inline_message_id:
                    await context.bot.edit_message_text("📤 Uploading to Telegram...", inline_message_id=query.inline_message_id)
                elif query.message:
                    await query.edit_message_text("📤 Uploading to Telegram...")

                try:
                    # Upload video to user's chat or group
                    if query.message:
                        with open(final_path, 'rb') as video_file:
                            await query.message.reply_video(
                                video=video_file,
                                supports_streaming=True,
                                caption="Here is your video! 🎥",
                                write_timeout=120
                            )
                        await query.message.delete()
                    elif query.inline_message_id:
                        # For inline messages in 1-on-1 private chats, send video to the user directly
                        with open(final_path, 'rb') as video_file:
                            msg = await context.bot.send_video(
                                chat_id=user_id,
                                video=video_file,
                                supports_streaming=True,
                                caption=f"Here is your downloaded video from {url}! 🎥",
                                write_timeout=120
                            )
                        await context.bot.edit_message_text(
                            f"✅ Video downloaded! Sent directly to your bot DM: [Open Bot](https://t.me/{context.bot.username})",
                            inline_message_id=query.inline_message_id,
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.exception(f"Failed to upload video to telegram: {e}")
                    if query.inline_message_id:
                        await context.bot.edit_message_text(f"❌ Failed to upload video: {str(e)}", inline_message_id=query.inline_message_id)
                    elif query.message:
                        await query.edit_message_text(f"❌ Failed to upload video: {str(e)}")
                finally:
                    if final_path and os.path.exists(final_path):
                        try:
                            os.remove(final_path)
                            logger.info(f"Cleaned up temp video file: {final_path}")
                        except OSError as e:
                            logger.error(f"Error removing temp file {final_path}: {e}")
