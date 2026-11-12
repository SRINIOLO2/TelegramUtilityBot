# TelegramUtilityBot (`@metahaterbot`)

A fast, modular Telegram utility bot that downloads, uncrops, and optimizes media from **Instagram**, **Facebook**, **TikTok**, and **YouTube** for seamless inline playback across iOS, Android, Desktop, and Web—in Bot DMs, group chats, and 1-on-1 private chats.

---

## ✨ Features & Supported Platforms

### 1. Supported Media & URLs
- **Instagram**:
  - Reels (`/reel/<id>`, `/reels/<id>`, `/<username>/reel/<id>`) with automatic iframe `contextJSON` fallback when anonymous GraphQL endpoints require login
  - Video & Photo Posts (`/p/<id>`, `/<username>/p/<id>`, `instagr.am/p/<id>`)
  - Mobile Share Links (`/share/<id>`, `/share/reel/<id>`, `/share/p/<id>`)
  - **Full-Scale Uncropped Images & Mixed Carousels**: Extracts highest-resolution `display_resources` and strips CDN square-crop (`c<x>.<y>.<w>.<h>a`) and resize (`s640x640`) directives across all slides (up to 10 photos/videos per post)
- **Facebook**:
  - Reels (`facebook.com/reel/<id>`, `facebook.com/share/r/<id>`)
  - Watch & Page Videos (`facebook.com/watch/?v=<id>`, `facebook.com/<page>/videos/<id>`, `facebook.com/share/v/<id>`, `fb.watch/<id>`)
- **TikTok**:
  - Videos (`/@username/video/<id>`, `/t/<id>`, `vm.tiktok.com/<id>`, `vt.tiktok.com/<id>`)
  - Photo Posts (`/@username/photo/<id>`)
  - Browser TLS impersonation via `curl-cffi`
- **YouTube (Manual Trigger Only)**:
  - Standard Videos (`youtube.com/watch?v=<id>`, `youtu.be/<id>`)
  - YouTube Shorts & Live (`youtube.com/shorts/<id>`, `youtube.com/live/<id>`)

---

## 📱 How to Use

### 1. Bot DM & Group Chats (Ephemeral Prompt)
- Whenever an **Instagram**, **Facebook**, or **TikTok** link is sent in a chat (in plain text, media captions, or hyperlink entities), the bot replies with a compact action bar:
  `[ 📥 Download <Platform> ]  [ ✖️ Dismiss ]`
- **45-Second Ephemeral Auto-Hide**: If the native Telegram embed already works and nobody taps download within **45 seconds**, the bot automatically deletes its prompt so the chat stays clean.
- Clicking **✖️ Dismiss** deletes the prompt immediately.
- **Expandable Post Captions**: Downloaded videos, photos, and media albums automatically include the original post's text/caption inside a collapsible Telegram quote block (`<blockquote expandable>...</blockquote>`).

### 2. Manual Downloads & YouTube Links (`/dl` or `@metahaterbot`)
To avoid cluttering chats when YouTube native embeds work, **YouTube links do not trigger automatic ephemeral prompts**. Manually download any YouTube, Instagram, Facebook, or TikTok link by:
- Sending `/dl <link>` (or `/download <link>`)
- Replying to any message containing a link with `/dl`, `/download`, or `@metahaterbot`

### 3. 1-on-1 Private Chats (Inline Mode with Interactive Carousel Pager)
Invoke `@metahaterbot` via **Inline Mode** in any 1-on-1 private conversation:
- Type `@metahaterbot <link>` and tap the popup card (`📥 Load <Platform> Media in Chat`).
- **Recent Links Memory**: Type `@metahaterbot ` (with a trailing space) to pick from your 5 most recently detected links.
- **In-Place Replacement & Carousel Pager**:
  - Single videos/photos morph directly in-place inside your 1-on-1 chat via `edit_message_media`.
  - Multi-slide Instagram carousels morph into Slide 1 and attach interactive **`[ ◀️ Prev ] [ 1 / N ] [ Next ▶️ ]`** buttons backed by cached Telegram `file_id`s so anyone in the chat can flip through full-resolution slides instantaneously.
  *(Note: Send `/start` to `@metahaterbot` in DM at least once so it can silently stage media via your Bot DM).*

---

## ⚙️ Technical Architecture

- **`services/url_patterns.py`**: Centralized URL regex patterns, platform detection, and SSRF domain allowlist validation (`is_safe_social_url`).
- **`services/cache.py`**: Bounded LRU `MediaCache` storing canonical URLs, uploaded Telegram `file_id`s (for zero-bandwidth instant repeat downloads and carousel paging), post captions, and recent per-user links.
- **`services/downloader.py`**: `yt-dlp` + `gallery-dl` + Instagram iframe `/embed/captioned/` parser (`Sec-Fetch-Dest: iframe`), CDN uncropper, and `ffmpeg` optimizer (`h264_nvenc` primary with automatic `libx264` CPU fallback).
- **`handlers/video.py`**: Message, inline query, and callback handlers with per-user locks (`1` active download/user) and global concurrency semaphore (`3` concurrent downloads).
- **`AGENTS.md`**: Developer & AI agent instructions and architectural invariants.

---

## 🧪 Running Tests

```bash
./venv/bin/python -m unittest discover -s tests -v
```

---

## 📄 License

Licensed under the [MIT License](LICENSE).
