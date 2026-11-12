# AGENTS.md — MetaHaterBot (`TelegramUtilityBot`) Agent Knowledge Base & Instructions

This document provides context, architectural invariants, and operational instructions for AI coding agents working on **TelegramUtilityBot (`@metahaterbot`)**.

---

## 1. Project Overview
MetaHaterBot is a Python 3.11+ Telegram utility bot (`python-telegram-bot` v21+, Bot API 7.x+) that downloads, uncrops, transcodes, and embeds media from **Instagram**, **Facebook**, **TikTok**, and **YouTube** directly into Telegram chats (Bot DMs, Group Chats, and 1-on-1 Private Chats via Inline Mode).

---

## 2. Module Responsibilities
- `main.py`: Entry point, `HTTPXRequest` pool tuning, `temp/` startup cleanup, `httpx`/`httpcore` log noise suppression, and handler registration (`/start`, `/help`, `/dl`, `/download`, inline queries, callback queries).
- `services/url_patterns.py`: Compiled regexes (`INSTAGRAM_PATTERN`, `TIKTOK_PATTERN`, `FACEBOOK_PATTERN`, `YOUTUBE_LINK_PATTERN`, `AUTO_LINK_PATTERN`, `SOCIAL_LINK_PATTERN`), platform label helper, and SSRF domain allowlist validation (`is_safe_social_url`).
- `services/cache.py`: Bounded LRU `MediaCache` mapping `url_hash` to canonical URLs, uploaded Telegram `file_id` lists (`[("photo" | "video", file_id), ...]`), extracted post captions, and recent per-user links.
- `services/downloader.py`: Media extraction and transcoding pipeline:
  - `resolve_share_url`: Follows redirect chains for `/share/reel/`, `/share/p/`, `/share/r/`, `/share/v/`, `fb.watch/`, and `vm.tiktok.com/`.
  - `_download_instagram_embed`: Requests `https://www.instagram.com/p/{shortcode}/embed/captioned/` **with `Sec-Fetch-Dest: iframe`, `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Site: cross-site` headers**. Without those headers, Instagram returns a blank JS splash page. Parses `contextJSON` (`GraphSidecar`, `GraphVideo`, `GraphImage`) for highest-resolution `display_resources` and direct `video_url` streams, falls back to `EmbeddedMediaImage`, strips square crop directives (`_uncrop_instagram_url`), and extracts the post caption (`_extract_caption_from_embed_html`).
  - `download`: Runs `yt-dlp` for Reels, TikTok, Facebook, and YouTube videos (<50 MB), storing extracted post descriptions.
  - `optimize_video`: Transcodes videos for mobile streaming (`h264_nvenc` primary with automatic `libx264` `superfast` fallback).
- `handlers/video.py`: Telegram message, inline query, and callback query orchestration:
  - Passive auto-detection (45s ephemeral auto-deleting prompt) for Instagram, Facebook, and TikTok.
  - Manual-only detection (`/dl`, `@metahaterbot`, inline query) for YouTube.
  - Expandable blockquote captions (`<blockquote expandable>...</blockquote>` with `parse_mode="HTML"`, truncated safely under Telegram's 1,024-char media caption limit).
  - 1-on-1 Inline Mode (`@metahaterbot <link>`): Stages slides silently in the user's Bot DM (`disable_notification=True`) to obtain `file_id`s, deletes staging messages immediately, replaces the inline message in-place via `edit_message_media`, and attaches `[ ◀️ Prev | 1/N | Next ▶️ ]` buttons (`page_<url_hash>_<idx>`) for multi-slide carousels.

---

## 3. Critical Technical Invariants (Do Not Break)
1. **Never Auto-Prompt on YouTube Links**: YouTube links must ONLY be matched by `YOUTUBE_LINK_PATTERN` / `SOCIAL_LINK_PATTERN` (manual `/dl`, `@metahaterbot`, or inline queries) — never in `AUTO_LINK_PATTERN`.
2. **Preserve `Sec-Fetch-Dest: iframe` Headers on Instagram Embeds**: Removing `Sec-Fetch-Dest: iframe` causes Instagram's `/embed/captioned/` endpoint to omit `contextJSON` and `EmbeddedMediaImage`, breaking both uncropped carousel extraction and the Reel login-wall fallback.
3. **Never Square-Crop Instagram Images**: Always pass Instagram CDN image URLs through `_uncrop_instagram_url` to strip `c<x>.<y>.<w>.<h>a` crop tokens and `s640x640` resize tokens from URL paths and `stp=` query parameters.
4. **Concurrency Limits**: Maintain 1 active download per user (`user_locks`) and at most 3 concurrent downloads globally (`global_semaphore`).
5. **Security & PII**:
   - Never commit `.env`, `cookies.txt`, bot tokens, user IDs, chat IDs, or downloaded media files.
   - Always validate URLs with `is_safe_social_url(url)` before making network requests or invoking `yt-dlp` / `gallery-dl`.

---

## 4. Testing & Deployment Workflow
- **Run Unit Tests Locally**:
  ```bash
  ./venv/bin/python -m unittest discover -s tests -v
  ```
- **Production Deployment**:
  - Hosted on TrueNAS Scale server (`sputnik`), managed via Dockhand (`environmentId: 1`, stack `metahaterbot`, `stackId: 26`).
  - Push code to `SRINIOLO2/TelegramUtilityBot` (`main`) and redeploy the `metahaterbot` stack in Dockhand.
