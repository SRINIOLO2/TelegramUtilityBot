# Changelog

All notable changes to **TelegramUtilityBot (`@metahaterbot`)** are documented in this file.

## [2.1.0] - 2026-11-11

### Added
- **Full-Scale Uncropped Instagram Images & Carousels**: Added `Sec-Fetch-Dest: iframe` request headers to Instagram's `/embed/captioned/` endpoint to restore full `contextJSON` and `EmbeddedMediaImage` payloads, selecting highest-resolution `display_resources` and stripping CDN square-crop (`c<x>.<y>.<w>.<h>a`) and resize (`s640x640`) directives (`_uncrop_instagram_url`) across all carousel slides (including mixed photo + video carousels).
- **Resilient Instagram Reel Fallback**: Added automatic `/embed/captioned/` `contextJSON` `video_url` stream extraction when `yt-dlp` encounters anonymous Instagram GraphQL `401 require_login` walls, plus redirect resolution (`resolve_share_url`) for `/share/reel/`, `/share/p/`, `/share/r/`, `/share/v/`, and `fb.watch/` URLs.
- **Facebook Video & Reel Support**: Added passive 45-second ephemeral auto-detection, `/dl` command support, and `@metahaterbot` inline mode support for `facebook.com/reel/`, `facebook.com/watch`, `facebook.com/share/r/`, `facebook.com/share/v/`, `facebook.com/<page>/videos/`, and `fb.watch/` links.
- **Expandable Blockquote Post Captions**: Extracted original media descriptions/captions (via `yt-dlp` metadata and Instagram `contextJSON` / `<div class="Caption">`) and attached them to uploaded videos, photos, and albums using Telegram's collapsible `<blockquote expandable>...</blockquote>` HTML format.
- **Interactive 1-on-1 Inline Carousel Pager**: Multi-slide Instagram carousels in 1-on-1 inline chats now include `[ ◀️ Prev ] [ 1 / N ] [ Next ▶️ ]` buttons (`page_<url_hash>_<idx>`) that flip slides instantaneously in-place via cached Telegram `file_id`s.
- **Instant Telegram `file_id` Caching (`services/cache.py`)**: Added bounded LRU `MediaCache` storing uploaded Telegram `file_id`s and captions by URL hash so repeat requests deliver immediately with zero re-downloading or re-encoding.
- **Modular URL & SSRF Validation (`services/url_patterns.py`)**: Extracted URL regexes and added `is_safe_social_url` hostname validation.
- **Repository Governance**: Added `AGENTS.md`, `LICENSE` (MIT), and expanded `.gitignore` PII rules.

### Fixed
- **Container Log Flooding**: Set `httpx` and `httpcore` loggers to `logging.WARNING` in `main.py` to eliminate ~8,640 daily `getUpdates` polling log lines, and added automatic startup cleanup for orphaned files in `temp/`.
- **Event Loop Safety**: Lazily initialized `VideoHandler.global_semaphore` on the active event loop for Python 3.9–3.12 compatibility.

---

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
