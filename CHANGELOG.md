# Changelog

All notable changes to **TelegramUtilityBot (`@metahaterbot`)** are documented in this file.

## [2.0.0] - 2026-10-25

### Added
- **Instagram Image & Carousel Support**: Automatically falls back to `gallery-dl` and Instagram's `/embed/captioned/` + OpenGraph scraper when an Instagram or TikTok link contains a single photo or multi-photo carousel, sending native Telegram photos or media albums (`reply_photo` / `reply_media_group`).
- **Manual YouTube Video & Shorts Downloads**: Added support for `youtube.com/watch?v=`, `youtu.be/`, and `youtube.com/shorts/` links when manually triggered via `/dl`, `/download`, `@metahaterbot` mention, or inline mode (`@metahaterbot <link>`).
- **45-Second Ephemeral Download Prompts**: Automatic Instagram and TikTok detection prompts now include a `✖️ Dismiss` button and automatically delete themselves after 45 seconds if untouched, keeping chats free of clutter when native embeds work.
- **In-Place 1-on-1 Chat Media Replacement**: Inline mode (`@metahaterbot <link>`) now stages media silently to obtain a `file_id`, replaces the inline message in-place with the playable video or photo via `edit_message_media`, and deletes the staging message from the user's Bot DM.
- **Slash Commands (`/dl`, `/download`)**: Added explicit command handlers so users can reply `/dl` to any link or send `/dl <link>`.
- **CPU Encoding Fallback**: Added automatic `libx264` (`superfast`) fallback in `DownloaderService.optimize_video` if NVIDIA `h264_nvenc` is unavailable.
- **Runtime Dependencies**: Added `nodejs` (for YouTube `yt-dlp` JS challenges), `yt-dlp[default,curl-cffi]` (for TikTok/Instagram browser TLS impersonation), and `gallery-dl` to `Dockerfile` and `requirements.txt`.

### Fixed
- **Instagram Reel & Share Link Regex (`AUTO_LINK_PATTERN`)**: Fixed missing matches for plural `/reels/<id>`, creator-prefixed paths (`/username/reel/<id>`, `/username/p/<id>`), single-segment share URLs (`/share/<id>`), and links inside media captions or hyperlink entities (`text_link`).
- **Idle Outbound `httpx.ConnectError` Crashes**: Configured dedicated `HTTPXRequest` connection pools and timeouts for API calls vs. polling, and registered a global error handler in `main.py`.

---

## [1.2.0] - 2026-08-28

### Added
- **Inline Mode (`InlineQueryHandler`)**: Enabled `@metahaterbot <link>` inline queries and recent link memory (last 5 links per user) for 1-on-1 chats.
- **Reply Link Detection**: Added support for detecting links inside replied-to messages.

### Fixed
- Fixed `cookies.txt` directory check (`os.path.isfile`) so empty Docker bind-mount directories do not crash `yt-dlp`.

---

## [1.1.0] - 2026-06-26

### Added
- **Per-User & Global Concurrency Controls**: Added per-user `asyncio.Lock` (1 active video per user) and global `asyncio.Semaphore(3)` (max 3 concurrent downloads).
- **Hardware-Accelerated Video Optimization**: Configured `ffmpeg` with `h264_nvenc`, variable framerate (`-vsync 2`), mono AAC audio (`-ac 1`), and `+faststart`.
