import logging
import os
import shutil
import subprocess
import yt_dlp
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class DownloaderService:
    def __init__(self, temp_dir: str = "temp"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        self.ffmpeg_available = shutil.which("ffmpeg") is not None
        if not self.ffmpeg_available:
            logger.warning("ffmpeg is not installed or not in PATH. Videos will not be optimized for Telegram mobile.")

    def download(self, url: str) -> Tuple[bool, Optional[str], str]:
        """
        Downloads a video from Instagram or TikTok using yt-dlp.
        Returns:
            (success, file_path, message)
        """
        # Set up yt-dlp options
        # We try to get mp4 natively to avoid unnecessary transcoding where possible
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": os.path.join(self.temp_dir, "%(id)s_raw.%(ext)s"),
            "max_filesize": 50 * 1024 * 1024,  # Telegram limit is 50MB
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": False,
            "nocheckcertificate": True,
            "socket_timeout": 30,  # Prevent hanging on connections
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Double-check if the file exists (sometimes extension changes during merge)
                base, _ = os.path.splitext(filename)
                possible_extensions = [".mp4", ".mkv", ".webm", ".3gp"]
                actual_file = None
                
                for ext in possible_extensions:
                    path = base + ext
                    if os.path.exists(path):
                        actual_file = path
                        break
                
                if not actual_file or not os.path.exists(actual_file):
                    return False, None, "File download completed, but could not locate the output file."
                
                # Check size
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

    def optimize_video(self, input_path: str) -> Tuple[str, bool]:
        """
        Optimizes video for Telegram mobile using ffmpeg.
        Forces H.264 video, AAC audio, yuv420p pixel format, and adds faststart.
        Returns:
            (output_path, was_optimized)
        """
        if not self.ffmpeg_available:
            logger.info("ffmpeg not available. Skipping optimization step.")
            return input_path, False

        # Create output path
        dir_name = os.path.dirname(input_path)
        base_name = os.path.basename(input_path)
        name_part, _ = os.path.splitext(base_name)
        # Remove the _raw suffix if present
        if name_part.endswith("_raw"):
            name_part = name_part[:-4]
            
        output_path = os.path.join(dir_name, f"{name_part}_optimized.mp4")

        # ffmpeg command to optimize:
        # -y: overwrite output
        # -c:v libx264: H.264 video codec
        # -preset superfast: transcode fast
        # -crf 24: reasonable quality / compression
        # -vf ...: scale down to 720p max (1280 width/height) if larger, force even dimensions
        # -pix_fmt yuv420p: wide compatibility
        # -c:a aac -b:a 128k: standard audio
        # -movflags +faststart: allows stream-play in Telegram before complete download
        command = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "h264_nvenc",
            "-preset", "fast",
            "-cq", "24",
            "-vsync", "2", # vfr: Variable framerate
            "-vf", "scale=min(720\\,iw):-2:force_original_aspect_ratio=decrease,format=yuv420p",
            "-c:a", "aac",
            "-ac", "1", # mono audio
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        try:
            logger.info(f"Running ffmpeg optimization for {input_path}")
            # Run command, redirect output
            result = subprocess.run(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=180
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                # Clean up raw file
                try:
                    os.remove(input_path)
                except OSError:
                    pass
                return output_path, True
            else:
                logger.error(f"ffmpeg failed with code {result.returncode}. Stderr: {result.stderr}")
                return input_path, False
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg optimization timed out after 3 minutes.")
            return input_path, False
        except Exception as e:
            logger.exception(f"Unexpected error running ffmpeg: {e}")
            return input_path, False
