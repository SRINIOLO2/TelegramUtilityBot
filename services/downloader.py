import html
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from typing import Dict, List, Optional, Tuple
import httpx
import yt_dlp
from services.url_patterns import is_safe_social_url

logger = logging.getLogger(__name__)

IFRAME_EMBED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "iframe",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
}


class DownloaderService:
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        self.ffmpeg_available = shutil.which("ffmpeg") is not None
        self.gallery_dl_available = shutil.which("gallery-dl") is not None
        self.last_captions: Dict[str, str] = {}
        if not self.ffmpeg_available:
            logger.warning("ffmpeg is not installed or not in PATH. Videos will not be optimized for Telegram mobile.")

    def _has_cookies(self) -> bool:
        return os.path.isfile("cookies.txt") and os.path.getsize("cookies.txt") > 0

    def get_caption(self, url: str) -> Optional[str]:
        return self.last_captions.get(url)

    def _store_caption(self, url: str, caption: Optional[str]) -> None:
        if caption and caption.strip():
            self.last_captions[url] = caption.strip()
            if len(self.last_captions) > 300:
                oldest_key = next(iter(self.last_captions))
                self.last_captions.pop(oldest_key, None)

    def resolve_share_url(self, url: str) -> str:
        """
        Resolves redirect chains for Instagram /share/, Facebook /share/ & fb.watch, and TikTok short links.
        """
        lower = url.lower()
        if any(tok in lower for tok in ("/share/", "fb.watch/", "vm.tiktok.com/", "vt.tiktok.com/", "/t/")):
            try:
                with httpx.Client(follow_redirects=True, timeout=12.0, headers=IFRAME_EMBED_HEADERS) as client:
                    resp = client.get(url)
                    resolved = str(resp.url)
                    if is_safe_social_url(resolved):
                        return resolved
            except Exception as e:
                logger.debug(f"Could not resolve share URL {url}: {e}")
        return url

    def download_media(self, url: str) -> Tuple[bool, List[Tuple[str, str]], str]:
        """
        Downloads media (video, single image, or multi-slide photo/video carousel) from
        Instagram, TikTok, Facebook, or YouTube.
        Returns:
            (success, media_items, message)
            where media_items is a list of (media_type, file_path) tuples ("video" or "photo").
        """
        if not is_safe_social_url(url):
            return False, [], "Unsupported or unsafe URL domain."

        resolved_url = self.resolve_share_url(url)
        is_ig = any(d in resolved_url.lower() for d in ("instagram.com", "instagr.am"))
        is_ig_post = is_ig and "/p/" in resolved_url.lower()

        # 1. For Instagram /p/ posts (single images & multi-slide carousels), try iframe embed extraction first
        # so full-scale uncropped carousels and mixed photo/video slides are preserved intact.
        if is_ig_post:
            ig_ok, ig_items, ig_msg = self._download_instagram_embed(url, resolved_url)
            if ig_ok and ig_items:
                return True, ig_items, ig_msg

        # 2. Attempt video download via yt-dlp (Reels, TikTok, Facebook, YouTube, or fallback)
        success, video_path, message = self.download(resolved_url, original_url=url)
        if success and video_path:
            return True, [("video", video_path)], message

        # 3. If yt-dlp failed on an Instagram Reel/Post (e.g., anonymous GraphQL 401 login wall) or TikTok photo post,
        # fall back to Instagram iframe embed extraction + gallery-dl.
        if is_ig:
            logger.info(f"yt-dlp did not return media for Instagram URL {resolved_url} ({message}). Trying iframe embed fallback...")
            ig_ok, ig_items, ig_msg = self._download_instagram_embed(url, resolved_url)
            if ig_ok and ig_items:
                return True, ig_items, ig_msg

        if any(domain in resolved_url.lower() for domain in ("instagram.com", "instagr.am", "tiktok.com")):
            logger.info(f"Attempting image extraction for {resolved_url}...")
            img_success, img_paths, img_msg = self.download_images(resolved_url, original_url=url)
            if img_success and img_paths:
                return True, [("photo", p) for p in img_paths], "Image download successful."

        return False, [], message

    def download(self, url: str, original_url: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
        """
        Downloads a video from Instagram, TikTok, Facebook, or YouTube using yt-dlp.
        Returns:
            (success, file_path, message)
        """
        job_id = uuid.uuid4().hex[:8]
        ydl_opts = {
            "format": (
                "bestvideo[height<=1080][filesize<45M][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=1080][ext=mp4]/best[ext=mp4]/best"
            ),
            "outtmpl": os.path.join(self.temp_dir, f"%(id)s_{job_id}_raw.%(ext)s"),
            "max_filesize": 50 * 1024 * 1024,  # Telegram bot upload limit is 50MB
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": False,
            "nocheckcertificate": True,
            "socket_timeout": 30,
            "js_runtimes": {"node": {}},
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        if self._has_cookies():
            ydl_opts["cookiefile"] = "cookies.txt"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                caption_text = info.get("description") or info.get("title")
                self._store_caption(original_url or url, caption_text)
                self._store_caption(url, caption_text)

                if "entries" in info and info["entries"]:
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        return False, None, "No downloadable media entries found."
                    filename = ydl.prepare_filename(entries[0])
                else:
                    filename = ydl.prepare_filename(info)

                base, _ = os.path.splitext(filename)
                possible_extensions = [".mp4", ".mkv", ".webm", ".3gp", ".mov"]
                actual_file = None

                for ext in possible_extensions:
                    path = base + ext
                    if os.path.exists(path):
                        actual_file = path
                        break

                if not actual_file and os.path.exists(filename):
                    actual_file = filename

                if not actual_file or not os.path.exists(actual_file):
                    return False, None, "File download completed, but could not locate the output file."

                file_size = os.path.getsize(actual_file)
                if file_size > 50 * 1024 * 1024:
                    os.remove(actual_file)
                    return False, None, f"Video size exceeds Telegram's 50MB bot upload limit ({file_size / (1024*1024):.1f}MB)."

                return True, actual_file, "Download successful."

        except yt_dlp.utils.MaxDownloadsReached:
            return False, None, "Download limit reached."
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp download error: {e}")
            return False, None, f"Failed to download video: {str(e)}"
        except Exception as e:
            logger.exception("Unexpected error during download:")
            return False, None, f"Unexpected downloader error: {str(e)}"

    @staticmethod
    def _uncrop_instagram_url(url: str) -> str:
        """
        Strips square crop (c<x>.<y>.<w>.<h>a) and downscale (s640x640, p640x640) directives
        from Instagram CDN image URLs so the full-resolution uncropped image is returned.
        """
        # 1. Clean path segments like /s640x640/ or /c0.180.1440.1440a/
        cleaned = re.sub(r"/(?:[sp]\d+x\d+|c\d+\.\d+\.\d+\.\d+a)(?=/)", "", url)

        # 2. Clean tokens inside stp= query parameter (e.g., stp=c288.0.864.864a_dst-jpg_e35_s640x640_tt6)
        def _clean_stp(match: re.Match) -> str:
            raw_stp = match.group(1)
            tokens = [
                t
                for t in raw_stp.split("_")
                if not re.match(r"^(?:c\d+\.\d+\.\d+\.\d+a|[sp]\d+x\d+)$", t)
            ]
            return f"stp={'_'.join(tokens)}" if tokens else ""

        cleaned = re.sub(r"stp=([^&\"'\s]+)", _clean_stp, cleaned)
        return cleaned

    @staticmethod
    def _extract_context_data_from_embed_html(page: str) -> dict:
        """
        Extracts shortcode_media dict from Instagram embed HTML (either window.__additionalDataLoaded or contextJSON).
        """
        data = {}
        add_match = re.search(r"window\.__additionalDataLoaded\([^,]+,\s*(\{.*?\})\);", page)
        if add_match:
            try:
                data = json.loads(add_match.group(1))
            except Exception:
                data = {}

        if not data:
            ctx_match = re.search(r'"contextJSON"\s*:\s*"((?:\\.|[^"\\])*)"', page)
            if ctx_match:
                try:
                    raw_json = json.loads(f'"{ctx_match.group(1)}"')
                    data = json.loads(raw_json)
                except Exception as e:
                    logger.debug(f"Failed parsing contextJSON: {e}")

        if isinstance(data, dict):
            return (
                data.get("gql_data", {}).get("shortcode_media")
                or data.get("graphql", {}).get("shortcode_media")
                or data.get("shortcode_media")
                or {}
            )
        return {}

    @classmethod
    def _best_image_from_node(cls, node: dict) -> Optional[str]:
        resources = node.get("display_resources")
        if isinstance(resources, list) and resources:
            best = max(resources, key=lambda r: r.get("config_width", 0) if isinstance(r, dict) else 0)
            if isinstance(best, dict) and best.get("src"):
                return cls._uncrop_instagram_url(best["src"])
        if node.get("display_url"):
            return cls._uncrop_instagram_url(node["display_url"])
        if node.get("thumbnail_src"):
            return cls._uncrop_instagram_url(node["thumbnail_src"])
        return None

    @classmethod
    def _parse_instagram_embed_html(cls, page: str) -> List[Tuple[str, str]]:
        """
        Parses Instagram's /embed/captioned/ HTML and returns an ordered list of
        ("photo" | "video", direct_url) items at full uncropped resolution.
        """
        items: List[Tuple[str, str]] = []
        media = cls._extract_context_data_from_embed_html(page)

        if media:
            sidecar = media.get("edge_sidecar_to_children", {}).get("edges", [])
            if sidecar:
                for edge in sidecar:
                    node = edge.get("node", {}) if isinstance(edge, dict) else {}
                    if node.get("is_video") and node.get("video_url"):
                        items.append(("video", node["video_url"]))
                    else:
                        img_url = cls._best_image_from_node(node)
                        if img_url:
                            items.append(("photo", img_url))
            elif media.get("is_video") and media.get("video_url"):
                items.append(("video", media["video_url"]))
            else:
                img_url = cls._best_image_from_node(media)
                if img_url:
                    items.append(("photo", img_url))

        # Fallback: single image post where Instagram sets contextJSON: null and renders EmbeddedMediaImage
        if not items:
            for img_match in re.finditer(
                r'<img[^>]+class="[^"]*EmbeddedMediaImage[^"]*"[^>]+src="([^"]+)"', page
            ):
                clean_url = cls._uncrop_instagram_url(html.unescape(img_match.group(1)))
                if ("photo", clean_url) not in items:
                    items.append(("photo", clean_url))

        return items

    @classmethod
    def _extract_caption_from_embed_html(cls, page: str) -> Optional[str]:
        """
        Extracts the post caption text from Instagram embed contextJSON or the <div class="Caption"> HTML block.
        """
        media = cls._extract_context_data_from_embed_html(page)
        if media:
            edges = media.get("edge_media_to_caption", {}).get("edges", [])
            if edges and isinstance(edges[0], dict):
                text = edges[0].get("node", {}).get("text")
                if text and text.strip():
                    return text.strip()
            if isinstance(media.get("caption"), str) and media["caption"].strip():
                return media["caption"].strip()

        cap_match = re.search(r'<div class="Caption">(.*?)</div>', page, re.DOTALL)
        if cap_match:
            raw_cap = cap_match.group(1)
            raw_cap = re.sub(r'<a class="CaptionUsername"[^>]*>.*?</a>', "", raw_cap, flags=re.DOTALL)
            raw_cap = re.sub(r'<div class="CaptionComments">.*', "", raw_cap, flags=re.DOTALL)
            raw_cap = re.sub(r"<br\s*/?>", "\n", raw_cap, flags=re.IGNORECASE)
            clean_cap = html.unescape(re.sub(r"<[^>]+>", "", raw_cap)).strip()
            if clean_cap:
                return clean_cap

        return None

    def _download_instagram_embed(
        self, original_url: str, resolved_url: str
    ) -> Tuple[bool, List[Tuple[str, str]], str]:
        """
        Fetches Instagram's /embed/captioned/ with Sec-Fetch-Dest: iframe headers, extracts
        all uncropped photos/videos and caption, and downloads them to temp_dir.
        """
        m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", resolved_url)
        if not m:
            return False, [], "Could not parse Instagram shortcode."

        shortcode = m.group(1)
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        job_id = uuid.uuid4().hex[:8]
        saved_items: List[Tuple[str, str]] = []

        try:
            with httpx.Client(follow_redirects=True, timeout=20.0, headers=IFRAME_EMBED_HEADERS) as client:
                resp = client.get(embed_url)
                if resp.status_code != 200:
                    return False, [], f"Instagram embed returned HTTP {resp.status_code}."

                page = resp.text
                caption = self._extract_caption_from_embed_html(page)
                self._store_caption(original_url, caption)
                self._store_caption(resolved_url, caption)

                media_specs = self._parse_instagram_embed_html(page)
                if not media_specs:
                    return False, [], "No media items found in Instagram embed."

                dl_headers = {
                    "User-Agent": IFRAME_EMBED_HEADERS["User-Agent"],
                    "Referer": "https://www.instagram.com/",
                }
                for idx, (m_type, m_url) in enumerate(media_specs[:10]):
                    ext = ".mp4" if m_type == "video" else ".jpg"
                    media_resp = client.get(m_url, headers=dl_headers)
                    if media_resp.status_code == 200 and media_resp.content:
                        if len(media_resp.content) > 50 * 1024 * 1024:
                            continue
                        out_path = os.path.join(self.temp_dir, f"ig_{job_id}_{idx}{ext}")
                        with open(out_path, "wb") as f:
                            f.write(media_resp.content)
                        saved_items.append((m_type, out_path))

            if saved_items:
                return True, saved_items, "Downloaded via Instagram iframe embed."
        except Exception as e:
            logger.exception(f"Instagram iframe embed extraction failed for {resolved_url}: {e}")

        return False, [], "Failed to download media from Instagram embed."

    def download_images(self, url: str, original_url: Optional[str] = None) -> Tuple[bool, List[str], str]:
        """
        Extracts and downloads image(s) from an Instagram post/carousel or TikTok photo post.
        Uses gallery-dl first, then falls back to Instagram's /embed/captioned/ endpoint.
        """
        job_id = uuid.uuid4().hex[:8]
        job_dir = os.path.join(self.temp_dir, f"img_{job_id}")
        os.makedirs(job_dir, exist_ok=True)

        # 1. Try gallery-dl if available
        if self.gallery_dl_available:
            cmd = [
                "gallery-dl",
                "--directory", job_dir,
                "--filename", "{num:>02}_{filename}.{extension}",
                "--range", "1-10",
            ]
            if self._has_cookies():
                cmd.extend(["--cookies", "cookies.txt"])
            cmd.append(url)

            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                downloaded = sorted(
                    os.path.join(job_dir, f)
                    for f in os.listdir(job_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                )
                if downloaded:
                    final_files = self._move_job_files(downloaded, job_dir, job_id)
                    return True, final_files, "Downloaded via gallery-dl."
                logger.info(f"gallery-dl produced no images (code {res.returncode}): {res.stderr.strip()}")
            except Exception as e:
                logger.warning(f"gallery-dl failed for {url}: {e}")

        # 2. Fallback: Instagram iframe embed extractor
        shutil.rmtree(job_dir, ignore_errors=True)
        ok, items, msg = self._download_instagram_embed(original_url or url, url)
        if ok and items:
            return True, [p for _, p in items], msg

        return False, [], "Could not extract images from link."

    def _move_job_files(self, files: List[str], job_dir: str, job_id: str) -> List[str]:
        final_files = []
        for idx, path in enumerate(files):
            ext = os.path.splitext(path)[1] or ".jpg"
            dest = os.path.join(self.temp_dir, f"media_{job_id}_{idx}{ext}")
            shutil.move(path, dest)
            final_files.append(dest)
        shutil.rmtree(job_dir, ignore_errors=True)
        return final_files

    def optimize_video(self, input_path: str) -> Tuple[str, bool]:
        """
        Optimizes video for Telegram mobile using ffmpeg.
        Attempts NVIDIA NVENC (h264_nvenc) first, with automatic CPU fallback (libx264).
        Returns:
            (output_path, was_optimized)
        """
        if not self.ffmpeg_available:
            logger.info("ffmpeg not available. Skipping optimization step.")
            return input_path, False

        dir_name = os.path.dirname(input_path)
        base_name = os.path.basename(input_path)
        name_part, _ = os.path.splitext(base_name)
        if name_part.endswith("_raw"):
            name_part = name_part[:-4]

        output_path = os.path.join(dir_name, f"{name_part}_optimized.mp4")

        nvenc_command = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "h264_nvenc",
            "-preset", "fast",
            "-cq", "24",
            "-vsync", "2",
            "-vf", "scale=min(720\\,iw):-2:force_original_aspect_ratio=decrease,format=yuv420p",
            "-c:a", "aac",
            "-ac", "1",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        cpu_command = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264",
            "-preset", "superfast",
            "-crf", "24",
            "-vsync", "2",
            "-vf", "scale=min(720\\,iw):-2:force_original_aspect_ratio=decrease,format=yuv420p",
            "-c:a", "aac",
            "-ac", "1",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        for idx, command in enumerate((nvenc_command, cpu_command)):
            encoder_name = "h264_nvenc" if idx == 0 else "libx264 (CPU fallback)"
            try:
                logger.info(f"Running ffmpeg optimization ({encoder_name}) for {input_path}")
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=180,
                )

                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    try:
                        os.remove(input_path)
                    except OSError:
                        pass
                    return output_path, True
                else:
                    logger.warning(f"ffmpeg ({encoder_name}) exited with {result.returncode}: {result.stderr[-300:]}")
            except subprocess.TimeoutExpired:
                logger.error(f"ffmpeg ({encoder_name}) timed out after 3 minutes.")
                break
            except Exception as e:
                logger.exception(f"Unexpected error running ffmpeg ({encoder_name}): {e}")

        return input_path, False
