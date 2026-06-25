import unittest

# Import the regex to test
from handlers.video import SOCIAL_LINK_PATTERN

class TestBotHandlers(unittest.TestCase):
    def test_social_link_regex(self):
        """
        Verify that the social link regex correctly detects valid Instagram and TikTok links.
        """
        valid_urls = [
            "https://www.instagram.com/reel/C321_abCD-X/",
            "http://instagram.com/reel/xyz123",
            "https://www.instagram.com/p/C_abc123XYZ/",
            "https://instagram.com/share/reel/C_abc/",
            "https://www.tiktok.com/@username/video/7312345678901234567",
            "https://vm.tiktok.com/ZM6PqR2s/",
            "https://vt.tiktok.com/ZS23456a/",
        ]
        
        invalid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://facebook.com/reel/123",
            "https://instagram.com/username",
            "https://tiktok.com/@username",
        ]

        for url in valid_urls:
            with self.subTest(url=url):
                self.assertIsNotNone(SOCIAL_LINK_PATTERN.search(url), f"Should match: {url}")

        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertIsNone(SOCIAL_LINK_PATTERN.search(url), f"Should NOT match: {url}")

if __name__ == "__main__":
    unittest.main()
