# TelegramUtilityBot

A fast, lightweight Telegram bot that listens for Instagram and TikTok links, downloads the videos on the fly, and uses hardware acceleration (NVENC) to optimize them for seamless inline mobile playback in Telegram.

## Setup Instructions (Dockhand / SputnikX)
This bot is designed to be deployed on Docker/Dockhand.

1. Set your `TELEGRAM_BOT_TOKEN` in the environment variables (in Dockhand, add it to the environment section).
2. Pull the latest code.
3. Because Dockhand caches images aggressively, any time you change the python code, bump the `image` version tag in `compose.yaml` (e.g. `v3` -> `v4`) to force a fresh build.
4. Deploy the stack.

## Technical Details & Architecture

### Concurrency Limits
To prevent server overload, the bot implements a strict queue system:
- **Per-User Limit:** A user can only process 1 video at a time.
- **Global Limit:** The server will only process a maximum of 3 videos concurrently. Additional requests wait in queue (`⏳ Queued (Server busy, please wait)...`).

### Video Optimization (FFmpeg & NVENC)
By default, the bot strips out unnecessary data and encodes the video using your server's Nvidia GPU to ensure the file plays perfectly and instantly on mobile devices.

**Current FFmpeg Settings (`services/downloader.py`):**
- `-c:v h264_nvenc`: Hardware-accelerated H.264 video encoding using the Nvidia GPU.
- `-preset fast` & `-cq 24`: Fast preset with a constant quality factor of 24 (excellent visual quality while reducing size).
- `-vsync 2`: Retains Variable Framerate (VFR).
- `-vf scale=min(720\,iw):-2...`: Downscales 4K/1080p videos to a maximum width of 720p to stay under Telegram's 50MB bot upload limit, while forcing even dimensions.
- `-c:a aac -ac 1 -b:a 128k`: Encodes audio to AAC Mono at 128kbps (perfect for social media voiceovers/music while saving space).
- `-movflags +faststart`: Moves the MOOV atom to the front of the file, allowing Telegram to stream the video instantly before the whole file is downloaded.

### How to modify or remove optimization
If you want to change these settings (for example, to increase quality or disable GPU encoding if you migrate servers), open `services/downloader.py` and locate the `command` list in the `optimize_video` function. 

To **remove optimization entirely**, simply uninstall `ffmpeg` from the host/container, or modify `optimize_video` in `services/downloader.py` to immediately `return input_path, False` at the top of the function.
