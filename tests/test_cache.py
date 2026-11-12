import unittest
from services.cache import MediaCache


class TestMediaCache(unittest.TestCase):
    def test_url_and_media_file_id_caching(self):
        cache = MediaCache(max_entries=5)
        url = "https://www.instagram.com/p/DfkkknjD6vm/"
        url_hash = cache.store_url(url)
        self.assertEqual(len(url_hash), 12)
        self.assertEqual(cache.get_url(url_hash), url)

        slides = [("photo", "file_id_1"), ("photo", "file_id_2")]
        cache.store_media_files(url_hash, slides, caption="Voyager 1 Golden Record")
        self.assertEqual(cache.get_media_files(url_hash), slides)
        self.assertEqual(cache.get_caption(url_hash), "Voyager 1 Golden Record")

    def test_lru_eviction(self):
        cache = MediaCache(max_entries=3)
        hashes = [cache.store_url(f"https://www.instagram.com/p/code{i}/") for i in range(4)]
        self.assertIsNone(cache.get_url(hashes[0]))
        self.assertIsNotNone(cache.get_url(hashes[3]))

    def test_recent_user_links_dedup_and_limit(self):
        cache = MediaCache()
        for i in range(7):
            cache.save_user_link(42, f"https://www.instagram.com/p/code{i}/")
        links = cache.get_user_links(42)
        self.assertEqual(len(links), 5)
        self.assertEqual(links[0], "https://www.instagram.com/p/code6/")


if __name__ == "__main__":
    unittest.main()
