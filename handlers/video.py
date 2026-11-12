import asyncio
import html
import logging
import os
import re
from typing import List, Optional, Tuple
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.ext import ContextTypes
from services.cache import MediaCache
from services.downloader import DownloaderService
from services.url_patterns import (
    AUTO_LINK_PATTERN,
    SOCIAL_LINK_PATTERN,
    YOUTUBE_LINK_PATTERN,
    get_platform_label,
    is_safe_social_url,
)

logger = logging.getLogger(__name__)

EPHEMERAL_TIMEOUT_SECONDS = 45


class VideoHandler:
    def __init__(self, downloader_service: DownloaderService):
        self.downloader = downloader_service
        self.cache = MediaCache(max_entries=500)
        # Alias for backward compatibility with existing tests/callers
        self.url_cache = self.cache
        # Track prompt message IDs that have been clicked so ephemeral auto-delete skips them
        self.claimed_prompts = set()

        # Concurrency protections (lazily initialized on the active event loop)
        self._global_semaphore: Optional[asyncio.Semaphore] = None
        self.user_locks = {}

    @property
    def global_semaphore(self) -> asyncio.Semaphore:
        if self._global_semaphore is None:
            self._global_semaphore = asyncio.Semaphore(3)
        return self._global_semaphore

    def get_user_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self.user_locks:
            self.user_locks[user_id] = asyncio.Lock()
        return self.user_locks[user_id]

    def save_user_link(self, user_id: int, url: str) -> None:
        self.cache.save_user_link(user_id, url)

    @staticmethod
    def _get_platform_label(url: str) -> str:
        return get_platform_label(url)

    @staticmethod
    def format_expandable_caption(caption: Optional[str]) -> Optional[str]:
        """
        Formats media post caption as an expandable Telegram blockquote (<blockquote expandable>...</blockquote>)
        using HTML parse mode, safely escaping entities and enforcing Telegram's 1,024-character media caption limit.
        """
        if not caption or not caption.strip():
            return None

        cleaned = caption.strip()
        if len(cleaned) > 900:
            cleaned = cleaned[:900].rstrip() + "…"

        escaped = html.escape(cleaned)
        # Guard in case HTML entity expansion pushes length near 1024
        max_inner = 1024 - len("<blockquote expandable>…</blockquote>")
        if len(escaped) > max_inner:
            escaped = escaped[:max_inner] + "…"

        return f"<blockquote expandable>{escaped}</blockquote>"

    @staticmethod
    def build_carousel_pager_keyboard(url_hash: str, current_idx: int, total: int) -> InlineKeyboardMarkup:
        """
        Builds an interactive 1-on-1 inline pager keyboard: [ ◀️ Prev ] [ 1 / N ] [ Next ▶️ ]
        with wrap-around navigation.
        """
        prev_idx = (current_idx - 1) % total
        next_idx = (current_idx + 1) % total
        keyboard = [
            [
                InlineKeyboardButton("◀️ Prev", callback_data=f"page_{url_hash}_{prev_idx}"),
                InlineKeyboardButton(f"{current_idx + 1} / {total}", callback_data="noop"),
                InlineKeyboardButton("Next ▶️", callback_data=f"page_{url_hash}_{next_idx}"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _extract_url_from_message(msg: Optional[Message], pattern: re.Pattern) -> Optional[str]:
        if not msg:
            return None

        # 1. Check message text and caption
        for content in (msg.text, msg.caption):
            if content:
                match = pattern.search(content)
                if match:
                    url = match.group(0)
                    if is_safe_social_url(url):
                        return url

        # 2. Check hyperlink entities (text_link / url)
        for entities in (msg.entities, msg.caption_entities):
            if entities:
                for ent in entities:
                    if ent.url:
                        match = pattern.search(ent.url)
                        if match:
                            url = match.group(0)
                            if is_safe_social_url(url):
                                return url

        return None

    async def _auto_delete_prompt(
        self, reply_msg: Message, prompt_key: str, delay: int = EPHEMERAL_TIMEOUT_SECONDS
    ) -> None:
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
        Supports Instagram, TikTok, Facebook, and YouTube links.
        """
        if not update.inline_query:
            return

        query = update.inline_query.query.strip()
        user_id = update.inline_query.from_user.id
        results = []

        # Case 1: User pasted a supported link in the inline query
        if query:
            match = SOCIAL_LINK_PATTERN.search(query)
            if match:
                url = match.group(0)
                if is_safe_social_url(url):
                    platform = self._get_platform_label(url)
                    self.save_user_link(user_id, url)
                    url_hash = self.cache.store_url(url)

                    keyboard = [
                        [InlineKeyboardButton(f"📥 Load {platform} Media", callback_data=f"dl_{url_hash}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    results.append(
                        InlineQueryResultArticle(
                            id=url_hash,
                            title=f"📥 Load {platform} Media in Chat",
                            description=f"Tap to embed video/carousel here: {url[:45]}...",
                            input_message_content=InputTextMessageContent(
                                f"🔗 *{platform} Link*\n{url}\n\n_Tap below to load media directly into this chat._",
                                parse_mode="Markdown",
                                link_preview_options=LinkPreviewOptions(is_disabled=True),
                            ),
                            reply_markup=reply_markup,
                        )
                    )

        # Case 2: User opened @metahaterbot with empty/non-matching query -> show recent links
        if not results:
            for idx, url in enumerate(self.cache.get_user_links(user_id)):
                platform = self._get_platform_label(url)
                url_hash = self.cache.store_url(url)
                keyboard = [
                    [InlineKeyboardButton(f"📥 Load {platform} Media", callback_data=f"dl_{url_hash}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                results.append(
                    InlineQueryResultArticle(
                        id=f"rec_{url_hash}_{idx}",
                        title=f"🕒 Recent {platform} Link #{idx + 1}",
                        description=f"{url[:50]}...",
                        input_message_content=InputTextMessageContent(
                            f"🔗 *{platform} Link*\n{url}\n\n_Tap below to load media directly into this chat._",
                            parse_mode="Markdown",
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                        ),
                        reply_markup=reply_markup,
                    )
                )

        await update.inline_query.answer(results, cache_time=0, is_personal=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Scans messages for links:
        - Auto-detects Instagram, TikTok, and Facebook links with a 45s ephemeral prompt.
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
            url = self._extract_url_from_message(msg, SOCIAL_LINK_PATTERN)
            if not url and msg.reply_to_message:
                url = self._extract_url_from_message(msg.reply_to_message, SOCIAL_LINK_PATTERN)
                target_msg = msg.reply_to_message
        else:
            # Automatic passive detection: Instagram, TikTok & Facebook (never auto-prompt on YouTube)
            url = self._extract_url_from_message(msg, AUTO_LINK_PATTERN)
            if not url and msg.reply_to_message and msg.chat.type == "private":
                url = self._extract_url_from_message(msg.reply_to_message, AUTO_LINK_PATTERN)
                target_msg = msg.reply_to_message

        if not url:
            if text.lower().startswith(("/dl", "/download")):
                await msg.reply_text(
                    "⚠️ No supported link found. Reply `/dl` to a message containing an Instagram, TikTok, Facebook, or YouTube link, or send `/dl <link>`.",
                    parse_mode="Markdown",
                )
            return

        platform = self._get_platform_label(url)
        user_id = update.effective_user.id if update.effective_user else 0
        logger.info(f"Detected {platform} link: {url} from user {user_id} (manual={is_manual_call})")

        if user_id:
            self.save_user_link(user_id, url)

        url_hash = self.cache.store_url(url)

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
        self.cache.bind_message(reply_msg.message_id, url)

        if not is_manual_call:
            asyncio.create_task(self._auto_delete_prompt(reply_msg, prompt_key, delay=EPHEMERAL_TIMEOUT_SECONDS))

    async def _handle_carousel_page(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, url_hash: str, target_idx: int
    ) -> None:
        """
        Flips to the requested slide index in a 1-on-1 inline carousel message using cached Telegram file_ids.
        """
        slides = self.cache.get_media_files(url_hash)
        if not slides:
            await query.answer("❌ Carousel cache expired. Please re-send the link.", show_alert=True)
            return

        total = len(slides)
        idx = target_idx % total
        m_type, file_id = slides[idx]
        formatted_caption = self.format_expandable_caption(self.cache.get_caption(url_hash))
        pager_kb = self.build_carousel_pager_keyboard(url_hash, idx, total)

        if m_type == "video":
            media_obj = InputMediaVideo(
                media=file_id,
                caption=formatted_caption,
                parse_mode="HTML" if formatted_caption else None,
                supports_streaming=True,
            )
        else:
            media_obj = InputMediaPhoto(
                media=file_id,
                caption=formatted_caption,
                parse_mode="HTML" if formatted_caption else None,
            )

        try:
            await query.answer(f"Slide {idx + 1} of {total}")
            if query.inline_message_id:
                await context.bot.edit_message_media(
                    inline_message_id=query.inline_message_id,
                    media=media_obj,
                    reply_markup=pager_kb,
                )
            elif query.message:
                await query.edit_message_media(
                    media=media_obj,
                    reply_markup=pager_kb,
                )
        except Exception as e:
            logger.debug(f"Carousel page update skipped: {e}")

    async def _deliver_from_cache(
        self,
        query: CallbackQuery,
        context: ContextTypes.DEFAULT_TYPE,
        url_hash: str,
        cached_slides: List[Tuple[str, str]],
        formatted_caption: Optional[str],
    ) -> None:
        """
        Instantly delivers media from cached Telegram file_ids without re-downloading.
        """
        if query.message:
            target_msg = query.message.reply_to_message or query.message
            if len(cached_slides) == 1:
                m_type, file_id = cached_slides[0]
                if m_type == "video":
                    await target_msg.reply_video(
                        video=file_id,
                        caption=formatted_caption,
                        parse_mode="HTML" if formatted_caption else None,
                        supports_streaming=True,
                    )
                else:
                    await target_msg.reply_photo(
                        photo=file_id,
                        caption=formatted_caption,
                        parse_mode="HTML" if formatted_caption else None,
                    )
            else:
                media_group = []
                for idx, (m_type, file_id) in enumerate(cached_slides[:10]):
                    cap = formatted_caption if idx == 0 else None
                    pm = "HTML" if cap else None
                    if m_type == "video":
                        media_group.append(
                            InputMediaVideo(media=file_id, caption=cap, parse_mode=pm, supports_streaming=True)
                        )
                    else:
                        media_group.append(InputMediaPhoto(media=file_id, caption=cap, parse_mode=pm))
                await target_msg.reply_media_group(media=media_group)

            try:
                await query.message.delete()
            except Exception:
                pass

        elif query.inline_message_id:
            m_type, file_id = cached_slides[0]
            pager_kb = (
                self.build_carousel_pager_keyboard(url_hash, 0, len(cached_slides))
                if len(cached_slides) > 1
                else None
            )
            if m_type == "video":
                media_obj = InputMediaVideo(
                    media=file_id,
                    caption=formatted_caption,
                    parse_mode="HTML" if formatted_caption else None,
                    supports_streaming=True,
                )
            else:
                media_obj = InputMediaPhoto(
                    media=file_id,
                    caption=formatted_caption,
                    parse_mode="HTML" if formatted_caption else None,
                )
            await context.bot.edit_message_media(
                inline_message_id=query.inline_message_id,
                media=media_obj,
                reply_markup=pager_kb,
            )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles inline button clicks for downloading media, flipping carousel slides, or dismissing prompts.
        """
        query = update.callback_query
        if not query:
            return

        data = query.data or ""

        if data == "noop":
            await query.answer()
            return

        if data.startswith("page_"):
            parts = data.split("_")
            if len(parts) == 3 and parts[2].isdigit():
                await self._handle_carousel_page(query, context, parts[1], int(parts[2]))
            else:
                await query.answer()
            return

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
        url_hash = None
        if data.startswith("dl_"):
            url_hash = data[3:]
            url = self.cache.get_url(url_hash)
        elif data == "download_video" and query.message:
            msg_id = str(query.message.message_id)
            url = self.cache.get_url(msg_id)

        if query.message:
            prompt_key = f"{query.message.chat_id}_{query.message.message_id}"
            self.claimed_prompts.add(prompt_key)
            if not url:
                url = self.cache.get_url(str(query.message.message_id))

        user_id = query.from_user.id

        if not url:
            await query.answer("❌ Link expired or not found. Please send the link again.", show_alert=True)
            return

        if not url_hash:
            url_hash = self.cache.store_url(url)

        # Fast path: deliver immediately if Telegram file_ids are already cached for this URL
        cached_slides = self.cache.get_media_files(url_hash)
        if cached_slides:
            await query.answer("⚡ Loaded from cache!")
            formatted_caption = self.format_expandable_caption(self.cache.get_caption(url_hash))
            try:
                await self._deliver_from_cache(query, context, url_hash, cached_slides, formatted_caption)
                return
            except Exception as e:
                logger.warning(f"Cached file_id delivery failed, falling back to fresh download: {e}")

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

                raw_caption = self.downloader.get_caption(url)
                formatted_caption = self.format_expandable_caption(raw_caption)

                final_items = []
                try:
                    for media_type, raw_path in media_items:
                        if media_type == "video":
                            await update_status("⚙️ Optimizing video for mobile...")
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
                    uploaded_slides: List[Tuple[str, str]] = []

                    # Delivery Branch 1: Normal Chat or Group Chat
                    if query.message:
                        target_msg = query.message.reply_to_message or query.message
                        if len(final_items) == 1:
                            m_type, f_path = final_items[0]
                            with open(f_path, "rb") as media_file:
                                if m_type == "video":
                                    sent = await target_msg.reply_video(
                                        video=media_file,
                                        caption=formatted_caption,
                                        parse_mode="HTML" if formatted_caption else None,
                                        supports_streaming=True,
                                        write_timeout=120,
                                    )
                                    if sent and getattr(sent, "video", None):
                                        uploaded_slides.append(("video", sent.video.file_id))
                                else:
                                    sent = await target_msg.reply_photo(
                                        photo=media_file,
                                        caption=formatted_caption,
                                        parse_mode="HTML" if formatted_caption else None,
                                        write_timeout=120,
                                    )
                                    if sent and getattr(sent, "photo", None):
                                        uploaded_slides.append(("photo", sent.photo[-1].file_id))
                        else:
                            media_group = []
                            open_files = []
                            try:
                                for idx, (m_type, f_path) in enumerate(final_items[:10]):
                                    f_obj = open(f_path, "rb")
                                    open_files.append(f_obj)
                                    cap = formatted_caption if idx == 0 else None
                                    pm = "HTML" if cap else None
                                    if m_type == "video":
                                        media_group.append(
                                            InputMediaVideo(
                                                media=f_obj,
                                                caption=cap,
                                                parse_mode=pm,
                                                supports_streaming=True,
                                            )
                                        )
                                    else:
                                        media_group.append(
                                            InputMediaPhoto(media=f_obj, caption=cap, parse_mode=pm)
                                        )
                                sent_msgs = await target_msg.reply_media_group(
                                    media=media_group, write_timeout=120
                                )
                                if sent_msgs:
                                    for s_msg in sent_msgs:
                                        if getattr(s_msg, "video", None):
                                            uploaded_slides.append(("video", s_msg.video.file_id))
                                        elif getattr(s_msg, "photo", None):
                                            uploaded_slides.append(("photo", s_msg.photo[-1].file_id))
                            finally:
                                for f_obj in open_files:
                                    f_obj.close()

                        if uploaded_slides:
                            self.cache.store_media_files(url_hash, uploaded_slides, caption=raw_caption)

                        try:
                            await query.message.delete()
                        except Exception:
                            pass

                    # Delivery Branch 2: Inline Mode in 1-on-1 Chats -> Stage & Replace In-Place with Pager!
                    elif query.inline_message_id:
                        for idx, (m_type, f_path) in enumerate(final_items[:10]):
                            if len(final_items) > 1:
                                await update_status(f"📤 Preparing slide {idx + 1} of {min(len(final_items), 10)}...")
                            with open(f_path, "rb") as media_file:
                                if m_type == "video":
                                    staged_msg = await context.bot.send_video(
                                        chat_id=user_id,
                                        video=media_file,
                                        supports_streaming=True,
                                        disable_notification=True,
                                        write_timeout=120,
                                    )
                                    uploaded_slides.append(("video", staged_msg.video.file_id))
                                else:
                                    staged_msg = await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=media_file,
                                        disable_notification=True,
                                        write_timeout=120,
                                    )
                                    uploaded_slides.append(("photo", staged_msg.photo[-1].file_id))

                            try:
                                await staged_msg.delete()
                            except Exception as del_err:
                                logger.debug(f"Could not delete staging message: {del_err}")

                        if uploaded_slides:
                            self.cache.store_media_files(url_hash, uploaded_slides, caption=raw_caption)
                            first_type, first_file_id = uploaded_slides[0]
                            pager_kb = (
                                self.build_carousel_pager_keyboard(url_hash, 0, len(uploaded_slides))
                                if len(uploaded_slides) > 1
                                else None
                            )
                            if first_type == "video":
                                first_media = InputMediaVideo(
                                    media=first_file_id,
                                    caption=formatted_caption,
                                    parse_mode="HTML" if formatted_caption else None,
                                    supports_streaming=True,
                                )
                            else:
                                first_media = InputMediaPhoto(
                                    media=first_file_id,
                                    caption=formatted_caption,
                                    parse_mode="HTML" if formatted_caption else None,
                                )
                            await context.bot.edit_message_media(
                                inline_message_id=query.inline_message_id,
                                media=first_media,
                                reply_markup=pager_kb,
                            )

                except Exception as e:
                    logger.exception(f"Failed to upload media to Telegram: {e}")
                    await update_status(f"❌ Failed to upload media: {str(e)}")
                finally:
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
