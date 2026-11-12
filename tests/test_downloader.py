import json
import unittest
from services.downloader import DownloaderService


class TestDownloaderInstagramExtraction(unittest.TestCase):
    def setUp(self):
        self.downloader = DownloaderService("temp")

    def test_uncrop_instagram_url_strips_crop_and_square_resize(self):
        cropped = (
            "https://scontent.cdninstagram.com/v/t51.82787-15/896_n.jpg"
            "?stp=c288.0.864.864a_dst-jpg_e35_s640x640_tt6&_nc_cat=1"
        )
        uncropped = self.downloader._uncrop_instagram_url(cropped)
        self.assertNotIn("c288.0.864.864a", uncropped)
        self.assertNotIn("s640x640", uncropped)
        self.assertIn("stp=dst-jpg_e35_tt6", uncropped)

        path_cropped = "https://scontent.cdninstagram.com/v/t51.2885-15/s640x640/c0.180.1440.1440a/12345_n.jpg?_nc_cat=1"
        path_uncropped = self.downloader._uncrop_instagram_url(path_cropped)
        self.assertNotIn("/s640x640/", path_uncropped)
        self.assertNotIn("/c0.180.1440.1440a/", path_uncropped)

    def test_parse_instagram_embed_html_extracts_full_scale_carousel_slides(self):
        context_obj = {
            "gql_data": {
                "shortcode_media": {
                    "__typename": "GraphSidecar",
                    "edge_media_to_caption": {
                        "edges": [{"node": {"text": "The sounds of Earth have traveled far."}}]
                    },
                    "edge_sidecar_to_children": {
                        "edges": [
                            {
                                "node": {
                                    "is_video": False,
                                    "display_url": "https://cdn.ig/slide1_1080.jpg",
                                    "display_resources": [
                                        {"src": "https://cdn.ig/slide1_640.jpg", "config_width": 640, "config_height": 638},
                                        {"src": "https://cdn.ig/slide1_1975.jpg", "config_width": 1975, "config_height": 1970},
                                    ],
                                }
                            },
                            {
                                "node": {
                                    "is_video": True,
                                    "video_url": "https://cdn.ig/slide2_video.mp4",
                                    "display_url": "https://cdn.ig/slide2_thumb.jpg",
                                }
                            },
                        ]
                    },
                }
            }
        }
        escaped_json = json.dumps(json.dumps(context_obj))[1:-1]
        html_page = f'<script>"contextJSON":"{escaped_json}"</script>'
        items = self.downloader._parse_instagram_embed_html(html_page)
        self.assertEqual(
            items,
            [
                ("photo", "https://cdn.ig/slide1_1975.jpg"),
                ("video", "https://cdn.ig/slide2_video.mp4"),
            ],
        )
        caption = self.downloader._extract_caption_from_embed_html(html_page)
        self.assertEqual(caption, "The sounds of Earth have traveled far.")

    def test_parse_instagram_embed_html_extracts_reel_video_url(self):
        context_obj = {
            "gql_data": {
                "shortcode_media": {
                    "__typename": "GraphVideo",
                    "is_video": True,
                    "video_url": "https://cdn.ig/reel_hd.mp4",
                }
            }
        }
        escaped_json = json.dumps(json.dumps(context_obj))[1:-1]
        html_page = f'<script>"contextJSON":"{escaped_json}"</script>'
        items = self.downloader._parse_instagram_embed_html(html_page)
        self.assertEqual(items, [("video", "https://cdn.ig/reel_hd.mp4")])

    def test_parse_instagram_embed_html_single_image_and_html_caption(self):
        html_page = (
            '<img class="EmbeddedMediaImage" src="https://scontent.cdninstagram.com/v/t51.82787-15/896_n.jpg'
            '?stp=c288.0.864.864a_dst-jpg_e35_s640x640_tt6&amp;_nc_cat=1" />'
            '<div class="Caption">'
            '<a class="CaptionUsername" href="https://www.instagram.com/nasa/">nasa</a>'
            'How&#x2019;s that for a starburst?<br /><br />Found in this distant spiral galaxy.'
            '<div class="CaptionComments">View all 120 comments</div>'
            '</div>'
        )
        items = self.downloader._parse_instagram_embed_html(html_page)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], "photo")
        self.assertIn("stp=dst-jpg_e35_tt6", items[0][1])
        self.assertNotIn("s640x640", items[0][1])

        caption = self.downloader._extract_caption_from_embed_html(html_page)
        self.assertEqual(caption, "How’s that for a starburst?\n\nFound in this distant spiral galaxy.")


if __name__ == "__main__":
    unittest.main()
