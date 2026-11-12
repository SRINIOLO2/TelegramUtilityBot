import unittest
from services.url_patterns import (
    AUTO_LINK_PATTERN,
    SOCIAL_LINK_PATTERN,
    YOUTUBE_LINK_PATTERN,
    get_platform_label,
    is_safe_social_url,
)


class TestUrlPatterns(unittest.TestCase):
    def test_auto_link_pattern_matches_ig_tiktok_facebook(self):
        auto_urls = [
            "https://www.instagram.com/reel/C321_abCD-X/",
            "https://www.instagram.com/reels/C321_abCD-X/",
            "https://www.instagram.com/p/C_abc123XYZ/?img_index=1",
            "https://instagram.com/share/reel/C_abc/",
            "https://instagram.com/share/p/C_abc/",
            "https://www.tiktok.com/@username/video/7312345678901234567",
            "https://www.tiktok.com/@username/photo/7312345678901234567",
            "https://vm.tiktok.com/ZM6PqR2s/",
            "https://www.facebook.com/reel/123456789012345/",
            "https://www.facebook.com/watch/?v=123456789012345",
            "https://www.facebook.com/watch?v=123456789012345",
            "https://www.facebook.com/share/r/1A2B3C4D5E/",
            "https://www.facebook.com/share/v/1A2B3C4D5E/",
            "https://www.facebook.com/nasa/videos/123456789012345/",
            "https://fb.watch/xYz123AbC/",
        ]
        for url in auto_urls:
            with self.subTest(url=url):
                self.assertIsNotNone(AUTO_LINK_PATTERN.search(url), f"AUTO should match {url}")
                self.assertIsNotNone(SOCIAL_LINK_PATTERN.search(url), f"SOCIAL should match {url}")

    def test_youtube_is_manual_only(self):
        yt_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abcDEF12345",
        ]
        for url in yt_urls:
            with self.subTest(url=url):
                self.assertIsNone(AUTO_LINK_PATTERN.search(url), f"AUTO should NOT match {url}")
                self.assertIsNotNone(YOUTUBE_LINK_PATTERN.search(url), f"YOUTUBE should match {url}")
                self.assertIsNotNone(SOCIAL_LINK_PATTERN.search(url), f"SOCIAL should match {url}")

    def test_platform_labels_and_ssrf_safety(self):
        self.assertEqual(get_platform_label("https://www.facebook.com/reel/123"), "Facebook")
        self.assertEqual(get_platform_label("https://fb.watch/abc/"), "Facebook")
        self.assertEqual(get_platform_label("https://www.instagram.com/p/abc/"), "Instagram")
        self.assertEqual(get_platform_label("https://www.tiktok.com/@u/video/123"), "TikTok")
        self.assertEqual(get_platform_label("https://youtu.be/abc123xyz"), "YouTube")
        self.assertTrue(is_safe_social_url("https://www.facebook.com/reel/123"))
        self.assertTrue(is_safe_social_url("https://fb.watch/abc123/"))
        self.assertFalse(is_safe_social_url("http://127.0.0.1/reel/123"))
        self.assertFalse(is_safe_social_url("https://evil.example.com/instagram.com/p/123"))


if __name__ == "__main__":
    unittest.main()
