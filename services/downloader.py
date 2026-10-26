import html
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
import httpx
import yt_dlp
from typing import Tuple, Optional, List

logger = logging.getLogger(__name__)


class DownloaderService:
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        self.ffmpeg_available = shutil.which("ffmpeg") is not None
        self.gallery_dl_available = shutil.which("gallery-dl") is not None
        if not self.ffmpeg_available:
            logger.warning("ffmpeg is not installed or not in PATH. Videos will not be optimized for Telegram mobile.")

    def _has_cookies(self) -> bool:
        return os.path.isfile("cookies.txt") and os.path.getsize("cookies.txt") > 0

    def download_media(self, url: str) -> Tuple[bool, List[Tuple[str, str]], str]:
        """
        Downloads media (video, single image, or image carousel) from Instagram, TikTok, or YouTube.
        Returns:
            (success, media_items, message)
            where media_items is a list of (media_type, file_path) tuples ("video" or "photo").
        """
        # First attempt video download via yt-dlp
        success, video_path, message = self.download(url)
        if success and video_path:
            return True, [("video", video_path)], message

        # If yt-dlp failed on an Instagram or TikTok link (e.g. "No video formats found" for an image post),
        # try extracting image(s) via gallery-dl / Instagram embed / OpenGraph fallback.
        if any(domain in url.lower() for domain in ("instagram.com", "instagr.am", "tiktok.com")):
            logger.info(f"yt-dlp did not return video for {url} ({message}). Attempting image extraction...")
            img_success, img_paths, img_msg = self.download_images(url)
            if img_success and img_paths:
                return True, [("photo", p) for p in img_paths], "Image download successful."

        return False, [], message

    def download(self, url: str) -> Tuple[bool, Optional[str], str]:
        """
        Downloads a video from Instagram, TikTok, or YouTube using yt-dlp.
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
                if "entries" in info and info["entries"]:
                    # If playlist/carousel with video entries, pick the first video entry
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

    def download_images(self, url: str) -> Tuple[bool, List[str], str]:
        """
        Extracts and downloads image(s) from an Instagram post/carousel or TikTok photo post.
        Uses gallery-dl first, then falls back to Instagram's /embed/captioned/ endpoint and OpenGraph tags.
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

        # 2. Fallback: Resolve redirects and scrape Instagram embed / OpenGraph image URLs
        try:
            image_urls = self._extract_instagram_image_urls(url)
            if image_urls:
                saved_paths = []
                with httpx.Client(follow_redirects=True, timeout=20.0) as client:
                    for idx, img_url in enumerate(image_urls[:10]):
                        resp = client.get(
                            img_url,
                            headers={
                                "User-Agent": (
                                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                                ),
                                "Referer": "https://www.instagram.com/",
                            },
                        )
                        if resp.status_code == 200 and resp.content:
                            out_path = os.path.join(self.temp_dir, f"ig_{job_id}_{idx}.jpg")
                            with open(out_path, "wb") as f:
                                f.write(resp.content)
                            saved_paths.append(out_path)

                shutil.rmtree(job_dir, ignore_errors=True)
                if saved_paths:
                    return True, saved_paths, "Downloaded via Instagram embed fallback."
        except Exception as e:
            logger.exception(f"Fallback image extraction failed for {url}: {e}")

        shutil.rmtree(job_dir, ignore_errors=True)
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

    def _extract_instagram_image_urls(self, url: str) -> List[str]:
        """
        Resolves Instagram URLs (including /share/ links) and extracts high-res image URLs
        from Instagram's public /embed/captioned/ endpoint or OpenGraph meta tags.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        image_urls: List[str] = []

        with httpx.Client(follow_redirects=True, timeout=15.0, headers=headers) as client:
            # Resolve /share/ or short links first
            try:
                head_resp = client.get(url)
                resolved_url = str(head_resp.url)
            except Exception:
                resolved_url = url

            # Extract shortcode from URL
            m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", resolved_url)
            shortcode = m.group(1) if m else None

            if shortcode:
                embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
                resp = client.get(embed_url)
                if resp.status_code == 200:
                    page = resp.text
                    # Check for contextJSON inside the embed page (contains full carousel slides)
                    ctx_match = re.search(r'window\.__additionalDataLoaded\([^,]+,\s*(\{.*?\})\);', page)
                    if not ctx_match:
                        ctx_match = re.search(r'"contextJSON"\s*:\s*"((?:\\.|[^"\\])*)"', page)
                        if ctx_match:
                            try:
                                raw_json = json.loads(f'"{ctx_match.group(1)}"')
                                data = json.loads(raw_json)
                                media = data.get("gql_data", {}).get("shortcode_media") or data.get("shortcode_media") or {}
                                sidecar = media.get("edge_sidecar_to_children", {}).get("edges", [])
                                if sidecar:
                                    for edge in sidecar:
                                        node = edge.get("node", {})
                                        if not node.get("is_video") and node.get("display_url"):
                                            image_urls.append(node["display_url"])
                                elif media.get("display_url"):
                                    image_urls.append(media["display_url"])
                            except Exception as e:
                                logger.debug(f"Failed parsing contextJSON: {e}")

                    # Fallback to EmbeddedMediaImage img tags in the embed HTML
                    if not image_urls:
                        for img_match in re.finditer(
                            r'<img[^>]+class="[^"]*EmbeddedMediaImage[^"]*"[^>]+src="([^"]+)"', page
                        ):
                            clean_url = html.unescape(img_match.group(1))
                            if clean_url not in image_urls:
                                image_urls.append(clean_url)

            # 3. Last resort: OpenGraph og:image via crawler User-Agent
            if not image_urls:
                crawler_resp = client.get(
                    resolved_url,
                    headers={"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"},
                )
                if crawler_resp.status_code == 200:
                    og_match = re.search(
                        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', crawler_resp.text, re.IGNORECASE
                    )
                    if og_match:
                        image_urls.append(html.unescape(og_match.group(1)))

        return image_urls

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
