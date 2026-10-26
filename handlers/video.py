import asyncio
import hashlib
import logging
import os
import re
from typing import Optional
from telegram import (
    Update,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InputMediaVideo,
    InputMediaPhoto,
)
from telegram.ext import ContextTypes
from services.downloader import DownloaderService

logger = logging.getLogger(__name__)

# Auto-detected links (Instagram Reels/Posts/Shares/Stories and TikTok Videos/Photos)
AUTO_LINK_PATTERN = re.compile(
    r"(https?://(?:www\.)?instagram\.com/(?:[A-Za-z0-9._]+/)?(?:p|reel|reels|tv)/[A-Za-z0-9-_]+"
    r"|https?://(?:www\.)?instagram\.com/share/(?:(?:p|reel|reels|tv)/)?[A-Za-z0-9-_]+"
    r"|https?://(?:www\.)?instagram\.com/stories/[A-Za-z0-9._]+/[0-9]+"
    r"|https?://instagr\.am/p/[A-Za-z0-9-_]+"
    r"|https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/(?:video|photo)/[0-9]+"
    r"|https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9_-]+"
    r"|https?://(?:vm|vt|v|m)\.tiktok\.com/(?:v/)?[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# Manual-only links (YouTube Watch, Shorts, Live, and youtu.be)
YOUTUBE_LINK_PATTERN = re.compile(
    r"(https?://(?:(?:www|m)\.)?youtube\.com/(?:watch\?[^\s\"'<>]*v=|shorts/|live/)[A-Za-z0-9_-]+"
    r"|https?://youtu\.be/[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# Combined pattern for manual commands (/dl), bot mentions (@metahaterbot), and inline queries
SOCIAL_LINK_PATTERN = re.compile(
    f"{AUTO_LINK_PATTERN.pattern}|{YOUTUBE_LINK_PATTERN.pattern}",
    re.IGNORECASE,
)

EPHEMERAL_TIMEOUT_SECONDS = 45


class VideoHandler:
    def __init__(self, downloader_service: DownloaderService):
        self.downloader = downloader_service
        # Cache to store the URL mapped to the message ID or callback query hash
        self.url_cache = {}
        # Store recent links per user for quick inline access
        self.recent_user_links = {}
        # Track prompt message IDs that have been clicked so ephemeral auto-delete skips them
        self.claimed_prompts = set()

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
        self.recent_user_links[user_id] = self.recent_user_links[user_id][:5]

    @staticmethod
    def _extract_url_from_message(msg: Optional[Message], pattern: re.Pattern) -> Optional[str]:
        if not msg:
            return None

        # 1. Check message text and caption
        for content in (msg.text, msg.caption):
            if content:
                match = pattern.search(content)
                if match:
                    return match.group(0)

        # 2. Check hyperlink entities (text_link / url)
        for entities in (msg.entities, msg.caption_entities):
            if entities:
                for ent in entities:
                    if ent.url:
                        match = pattern.search(ent.url)
                        if match:
                            return match.group(0)

        return None

    @staticmethod
    def _get_platform_label(url: str) -> str:
        lower = url.lower()
        if "instagram.com" in lower or "instagr.am" in lower:
            return "Instagram"
        if "tiktok.com" in lower:
            return "TikTok"
        if "youtube.com" in lower or "youtu.be" in lower:
            return "YouTube"
        return "Media"

    async def _auto_delete_prompt(self, reply_msg: Message, prompt_key: str, delay: int = EPHEMERAL_TIMEOUT_SECONDS) -> None:
        """
        Deletes the ephemeral download prompt after `delay` seconds if the user hasn't clicked Download.
        """
        try:
            await asyncio.sleep(delay)
            if prompt_key not in self.claimed_prompts:
                await reply_msg.delete()
                logger.info(f"Auto-deleted untouched ephemeral prompt {prompt_key} after {delay}s")
        except Exception as e:
            logger.debug(f"Could not auto-delete ephemeral prompt {prompt_key}: {e}")

    async def handle_inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles inline queries so users can type @metahaterbot <link> or just @metahaterbot in any 1-on-1 chat.
        Supports Instagram, TikTok, and YouTube links.
        """
        if not update.inline_query:
            return

        query = update.inline_query.query.strip()
        user_id = update.inline_query.from_user.id
        results = []

        # Case 1: User pasted a link (Instagram, TikTok, or YouTube) in the inline query
        if query:
            match = SOCIAL_LINK_PATTERN.search(query)
            if match:
                url = match.group(0)
                platform = self._get_platform_label(url)
                self.save_user_link(user_id, url)
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                self.url_cache[url_hash] = url

                keyboard = [
                    [InlineKeyboardButton(f"📥 Download {platform} Media", callback_data=f"dl_{url_hash}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                results.append(
                    InlineQueryResultArticle(
                        id=url_hash,
                        title=f"📥 Download {platform} Media",
                        description=f"Click to post & download in this chat: {url[:45]}...",
                        input_message_content=InputTextMessageContent(
                            f"🔗 *{platform} Link:*\n{url}\n\n_Tap below to load media directly into this chat._",
                            parse_mode="Markdown",
                        ),
                        reply_markup=reply_markup,
                    )
                )

        # Case 2: User opened @metahaterbot with empty/non-matching query -> show recent links
        if not results and user_id in self.recent_user_links:
            for idx, url in enumerate(self.recent_user_links[user_id]):
                platform = self._get_platform_label(url)
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                self.url_cache[url_hash] = url
                keyboard = [
                    [InlineKeyboardButton(f"📥 Download {platform} Media", callback_data=f"dl_{url_hash}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                results.append(
                    InlineQueryResultArticle(
                        id=f"rec_{url_hash}_{idx}",
                        title=f"🕒 Recent {platform} Link #{idx + 1}",
                        description=f"{url[:50]}...",
                        input_message_content=InputTextMessageContent(
                            f"🔗 *{platform} Link:*\n{url}\n\n_Tap below to load media directly into this chat._",
                            parse_mode="Markdown",
                        ),
                        reply_markup=reply_markup,
                    )
                )

        await update.inline_query.answer(results, cache_time=0, is_personal=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Scans messages for links:
        - Auto-detects Instagram & TikTok links with a 45s ephemeral prompt.
        - Detects YouTube (and replied-to links) when manually invoked via /dl, /download, or @metahaterbot.
        """
        msg = update.effective_message
        if not msg:
            return

        text = (msg.text or msg.caption or "").strip()
        bot_username = (context.bot.username or "metahaterbot").lower()

        is_manual_call = (
            text.lower().startswith(("/dl", "/download"))
            or f"@{bot_username}" in text.lower()
        )

        url = None
        target_msg = msg

        if is_manual_call:
            # Manual call: check current message first, then replied-to message, supporting YouTube + IG + TikTok
            url = self._extract_url_from_message(msg, SOCIAL_LINK_PATTERN)
            if not url and msg.reply_to_message:
                url = self._extract_url_from_message(msg.reply_to_message, SOCIAL_LINK_PATTERN)
                target_msg = msg.reply_to_message
        else:
            # Automatic passive detection: only Instagram & TikTok (never auto-prompt on YouTube)
            url = self._extract_url_from_message(msg, AUTO_LINK_PATTERN)
            # Also support replying to an IG/TikTok link in DM
            if not url and msg.reply_to_message and msg.chat.type == "private":
                url = self._extract_url_from_message(msg.reply_to_message, AUTO_LINK_PATTERN)
                target_msg = msg.reply_to_message

        if not url:
            if text.lower().startswith(("/dl", "/download")):
                await msg.reply_text(
                    "⚠️ No supported link found. Reply `/dl` to a message containing an Instagram, TikTok, or YouTube link, or send `/dl <link>`.",
                    parse_mode="Markdown",
                )
            return

        platform = self._get_platform_label(url)
        user_id = update.effective_user.id if update.effective_user else 0
        logger.info(f"Detected {platform} link: {url} from user {user_id} (manual={is_manual_call})")

        if user_id:
            self.save_user_link(user_id, url)

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        self.url_cache[url_hash] = url

        keyboard = [
            [
                InlineKeyboardButton(f"📥 Download {platform}", callback_data=f"dl_{url_hash}"),
                InlineKeyboardButton("✖️ Dismiss", callback_data=f"dismiss_{url_hash}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        prompt_text = (
            f"🎬 *{platform} link detected!* Tap below to download."
            if is_manual_call
            else f"🎬 *{platform} link detected!* _(Auto-hides in {EPHEMERAL_TIMEOUT_SECONDS}s)_"
        )

        reply_msg = await target_msg.reply_text(
            prompt_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

        prompt_key = f"{reply_msg.chat_id}_{reply_msg.message_id}"
        self.url_cache[str(reply_msg.message_id)] = url

        # Schedule ephemeral auto-delete if this was an automatic prompt
        if not is_manual_call:
            asyncio.create_task(self._auto_delete_prompt(reply_msg, prompt_key, delay=EPHEMERAL_TIMEOUT_SECONDS))

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles inline button clicks for downloading media or dismissing the ephemeral prompt.
        """
        query = update.callback_query
        if not query:
            return

        data = query.data or ""

        # Handle Dismiss button
        if data.startswith("dismiss_"):
            if query.message:
                prompt_key = f"{query.message.chat_id}_{query.message.message_id}"
                self.claimed_prompts.add(prompt_key)
                try:
                    await query.message.delete()
                except Exception:
                    pass
            await query.answer("Dismissed")
            return

        # Resolve URL from callback data
        url = None
        if data.startswith("dl_"):
            url_hash = data[3:]
            url = self.url_cache.get(url_hash)
        elif data == "download_video" and query.message:
            msg_id = str(query.message.message_id)
            url = self.url_cache.get(msg_id)

        if query.message:
            prompt_key = f"{query.message.chat_id}_{query.message.message_id}"
            self.claimed_prompts.add(prompt_key)
            if not url:
                url = self.url_cache.get(str(query.message.message_id))

        user_id = query.from_user.id

        if not url:
            await query.answer("❌ Link expired or not found. Please send the link again.", show_alert=True)
            return

        user_lock = self.get_user_lock(user_id)
        if user_lock.locked():
            await query.answer("⚠️ You already have a download in progress! Please wait.", show_alert=True)
            return

        await query.answer()

        async def update_status(status_text: str) -> None:
            try:
                if query.inline_message_id:
                    await context.bot.edit_message_text(
                        status_text,
                        inline_message_id=query.inline_message_id,
                    )
                elif query.message:
                    await query.edit_message_text(status_text)
            except Exception as e:
                logger.debug(f"Status update skipped: {e}")

        async with user_lock:
            if self.global_semaphore.locked():
                await update_status("⏳ Queued (Server busy, please wait)...")

            async with self.global_semaphore:
                await update_status("🔄 Downloading media...")

                loop = asyncio.get_running_loop()
                try:
                    success, media_items, message = await asyncio.wait_for(
                        loop.run_in_executor(None, self.downloader.download_media, url),
                        timeout=120,
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Download timed out for {url}")
                    await update_status("❌ Download timed out after 2 minutes.")
                    return

                if not success or not media_items:
                    logger.error(f"Download failed for {url}: {message}")
                    await update_status(f"❌ {message}")
                    return

                final_items = []
                try:
                    # Optimize any video items for mobile streaming
                    for media_type, raw_path in media_items:
                        if media_type == "video":
                            await update_status("⚙️ Optimizing video for mobile (NVENC)...")
                            try:
                                opt_path, _ = await asyncio.wait_for(
                                    loop.run_in_executor(None, self.downloader.optimize_video, raw_path),
                                    timeout=180,
                                )
                                final_items.append(("video", opt_path))
                            except asyncio.TimeoutError:
                                logger.error(f"Optimization timed out for {raw_path}")
                                if os.path.exists(raw_path):
                                    os.remove(raw_path)
                                await update_status("❌ Video optimization timed out.")
                                return
                        else:
                            final_items.append((media_type, raw_path))

                    await update_status("📤 Uploading to Telegram...")

                    # Delivery Branch 1: Normal Chat or Group Chat
                    if query.message:
                        target_msg = query.message.reply_to_message or query.message
                        if len(final_items) == 1:
                            m_type, f_path = final_items[0]
                            with open(f_path, "rb") as media_file:
                                if m_type == "video":
                                    await target_msg.reply_video(
                                        video=media_file,
                                        supports_streaming=True,
                                        write_timeout=120,
                                    )
                                else:
                                    await target_msg.reply_photo(
                                        photo=media_file,
                                        write_timeout=120,
                                    )
                        else:
                            # Multi-image carousel
                            media_group = []
                            open_files = []
                            try:
                                for m_type, f_path in final_items[:10]:
                                    f_obj = open(f_path, "rb")
                                    open_files.append(f_obj)
                                    if m_type == "video":
                                        media_group.append(InputMediaVideo(media=f_obj, supports_streaming=True))
                                    else:
                                        media_group.append(InputMediaPhoto(media=f_obj))
                                await target_msg.reply_media_group(media=media_group, write_timeout=120)
                            finally:
                                for f_obj in open_files:
                                    f_obj.close()

                        try:
                            await query.message.delete()
                        except Exception:
                            pass

                    # Delivery Branch 2: Inline Mode in 1-on-1 Chats -> Replace inline message in-place!
                    elif query.inline_message_id:
                        m_type, f_path = final_items[0]
                        with open(f_path, "rb") as media_file:
                            if m_type == "video":
                                staged_msg = await context.bot.send_video(
                                    chat_id=user_id,
                                    video=media_file,
                                    supports_streaming=True,
                                    disable_notification=True,
                                    write_timeout=120,
                                )
                                file_id = staged_msg.video.file_id
                                await context.bot.edit_message_media(
                                    inline_message_id=query.inline_message_id,
                                    media=InputMediaVideo(media=file_id, supports_streaming=True),
                                )
                            else:
                                staged_msg = await context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=media_file,
                                    disable_notification=True,
                                    write_timeout=120,
                                )
                                file_id = staged_msg.photo[-1].file_id
                                await context.bot.edit_message_media(
                                    inline_message_id=query.inline_message_id,
                                    media=InputMediaPhoto(media=file_id),
                                )

                        # Delete the temporary staging message from user's Bot DM so their Bot DM stays clean
                        try:
                            await staged_msg.delete()
                        except Exception as del_err:
                            logger.debug(f"Could not delete staging message: {del_err}")

                except Exception as e:
                    logger.exception(f"Failed to upload media to Telegram: {e}")
                    await update_status(f"❌ Failed to upload media: {str(e)}")
                finally:
                    # Clean up all temporary files
                    for _, f_path in final_items:
                        if f_path and os.path.exists(f_path):
                            try:
                                os.remove(f_path)
                                logger.info(f"Cleaned up temp file: {f_path}")
                            except OSError as e:
                                logger.error(f"Error removing temp file {f_path}: {e}")
                    for _, raw_path in media_items:
                        if raw_path and os.path.exists(raw_path):
                            try:
                                os.remove(raw_path)
                            except OSError:
                                pass
