import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from telegram import CallbackQuery, Message, Update, User
from handlers.video import VideoHandler, SOCIAL_LINK_PATTERN, AUTO_LINK_PATTERN
from services.downloader import DownloaderService


class TestBotHandlers(unittest.TestCase):
    def setUp(self):
        self.downloader = DownloaderService("temp")
        self.handler = VideoHandler(self.downloader)

    def test_social_link_regex_supports_ig_tiktok_fb_youtube(self):
        valid_auto = [
            "https://www.instagram.com/reel/C321_abCD-X/",
            "http://instagram.com/reel/xyz123",
            "https://www.instagram.com/p/C_abc123XYZ/",
            "https://instagram.com/share/reel/C_abc/",
            "https://www.tiktok.com/@username/video/7312345678901234567",
            "https://vm.tiktok.com/ZM6PqR2s/",
            "https://vt.tiktok.com/ZS23456a/",
            "https://www.facebook.com/reel/123456789/",
            "https://fb.watch/abc123xyz/",
        ]
        for url in valid_auto:
            with self.subTest(url=url):
                self.assertIsNotNone(AUTO_LINK_PATTERN.search(url), f"AUTO should match: {url}")
                self.assertIsNotNone(SOCIAL_LINK_PATTERN.search(url), f"SOCIAL should match: {url}")

        # YouTube matches SOCIAL_LINK_PATTERN (manual/inline) but NOT AUTO_LINK_PATTERN
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertIsNone(AUTO_LINK_PATTERN.search(yt_url))
        self.assertIsNotNone(SOCIAL_LINK_PATTERN.search(yt_url))

        invalid_urls = [
            "https://instagram.com/username",
            "https://tiktok.com/@username",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertIsNone(SOCIAL_LINK_PATTERN.search(url), f"Should NOT match: {url}")

    def test_carousel_pager_keyboard_wrap_around(self):
        kb = self.handler.build_carousel_pager_keyboard("abc123hash00", current_idx=0, total=4)
        buttons = kb.inline_keyboard[0]
        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0].callback_data, "page_abc123hash00_3")
        self.assertEqual(buttons[1].text, "1 / 4")
        self.assertEqual(buttons[2].callback_data, "page_abc123hash00_1")

    def test_format_expandable_caption_escapes_html_and_truncates(self):
        raw = "Hello <world> & friends!\nSecond line."
        formatted = self.handler.format_expandable_caption(raw)
        self.assertEqual(
            formatted,
            "<blockquote expandable>Hello &lt;world&gt; &amp; friends!\nSecond line.</blockquote>",
        )
        self.assertIsNone(self.handler.format_expandable_caption(None))
        self.assertIsNone(self.handler.format_expandable_caption("   "))

        long_raw = "A" * 1200
        long_formatted = self.handler.format_expandable_caption(long_raw)
        self.assertLessEqual(len(long_formatted), 1024)
        self.assertTrue(long_formatted.startswith("<blockquote expandable>"))
        self.assertTrue(long_formatted.endswith("…</blockquote>"))

    def test_inline_carousel_page_callback_edits_media_with_cached_file_id(self):
        url = "https://www.instagram.com/p/DfkkknjD6vm/"
        url_hash = self.handler.cache.store_url(url)
        self.handler.cache.store_media_files(
            url_hash,
            [("photo", "tg_file_slide_1"), ("video", "tg_file_slide_2")],
            caption="Voyager 1 post",
        )

        update = MagicMock(spec=Update)
        query = AsyncMock(spec=CallbackQuery)
        query.data = f"page_{url_hash}_1"
        query.inline_message_id = "inline_msg_999"
        query.message = None
        query.from_user = MagicMock(spec=User)
        query.from_user.id = 77
        update.callback_query = query

        context = MagicMock()
        context.bot.edit_message_media = AsyncMock()

        asyncio.run(self.handler.button_callback(update, context))

        context.bot.edit_message_media.assert_awaited_once()
        call_kwargs = context.bot.edit_message_media.call_args.kwargs
        self.assertEqual(call_kwargs["inline_message_id"], "inline_msg_999")
        self.assertEqual(call_kwargs["media"].media, "tg_file_slide_2")
        self.assertEqual(
            call_kwargs["media"].caption,
            "<blockquote expandable>Voyager 1 post</blockquote>",
        )
        self.assertEqual(
            call_kwargs["reply_markup"].inline_keyboard[0][1].text,
            "2 / 2",
        )


if __name__ == "__main__":
    unittest.main()
