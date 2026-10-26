# TelegramUtilityBot (`@metahaterbot`)

A fast, lightweight Telegram utility bot that downloads and optimizes media from **Instagram**, **TikTok**, and **YouTube** for seamless inline mobile playback in Telegram—across direct DMs, group chats, and 1-on-1 private chats.

---

## ✨ Features & Supported Platforms

### 1. Supported Media & URLs
- **Instagram**:
  - Reels (`/reel/<id>`, `/reels/<id>`, `/<username>/reel/<id>`)
  - Video & Photo Posts (`/p/<id>`, `/<username>/p/<id>`, `instagr.am/p/<id>`)
  - Mobile Share Links (`/share/<id>`, `/share/reel/<id>`, `/share/p/<id>`)
  - Single Images & Multi-Image Carousels (automatically detected via `gallery-dl` and Instagram `/embed/captioned/` + OpenGraph fallback, delivered as native Telegram photos or albums)
- **TikTok**:
  - Videos (`/@username/video/<id>`, `/t/<id>`, `vm.tiktok.com/<id>`, `vt.tiktok.com/<id>`)
  - Photo Posts (`/@username/photo/<id>`)
  - Browser TLS impersonation via `curl-cffi` to prevent rate-limiting
- **YouTube (Manual Trigger Only)**:
  - Standard Videos (`youtube.com/watch?v=<id>`, `youtu.be/<id>`)
  - YouTube Shorts (`youtube.com/shorts/<id>`)
  - Powered by `yt-dlp` with embedded `nodejs` runtime

---

## 📱 How to Use

### 1. Bot DM & Group Chats (Ephemeral Prompt)
- Whenever an **Instagram** or **TikTok** link is sent in a chat (either in plain text, media captions, or hyperlink entities), the bot replies with a compact action bar:
  `[ 📥 Download Instagram/TikTok ]  [ ✖️ Dismiss ]`
- **45-Second Ephemeral Auto-Hide**: If the native Telegram embed already works and nobody clicks download within **45 seconds**, the bot automatically deletes its prompt message so the chat remains clutter-free.
- Clicking **✖️ Dismiss** deletes the prompt immediately.

### 2. Manual Downloads & YouTube Links (`/dl` or `@metahaterbot`)
To avoid spamming chats when YouTube native embeds work, **YouTube links do not trigger automatic ephemeral prompts**. You can manually download any YouTube, Instagram, or TikTok link by:
- Sending `/dl <link>` (or `/download <link>`)
- Replying to any message containing a link with `/dl`, `/download`, or `@metahaterbot`

### 3. 1-on-1 Private Chats (Inline Mode with In-Place Media Replacement)
Because Telegram isolates private 1-on-1 chats from bots, you can invoke `@metahaterbot` via **Inline Mode** in any conversation:
- Type `@metahaterbot <link>` in any chat and tap the popup card (`📥 Download <Platform> Media`).
- **Recent Links Memory**: Type `@metahaterbot ` (with a trailing space and no link) to quickly pick from your 5 most recently detected links.
- **In-Place Replacement**: When you tap the download button on the inline message in your friend's chat, the bot stages the media via your Bot DM to obtain a Telegram `file_id`, calls `edit_message_media` to **transform the inline message directly into the playable video or photo inside the 1-on-1 chat**, and automatically deletes the temporary staging message from your Bot DM.
  *(Note: Ensure you have sent `/start` to `@metahaterbot` in DM at least once so it has permission to stage media via your DM).*

---

## ⚙️ Technical Architecture

### Concurrency & Rate Protection
- **Per-User Lock**: Each user can process **1 media download** at a time.
- **Global Semaphore**: A maximum of **3 downloads** run concurrently across the server; additional clicks wait in queue (`⏳ Queued (Server busy, please wait)...`).

### Video Optimization (`FFmpeg` NVENC + CPU Fallback)
Videos are transcoded for instant mobile streaming in Telegram while staying under the 50MB Bot API upload limit:
- **Primary Encoder**: `-c:v h264_nvenc -preset fast -cq 24` (NVIDIA hardware encoding)
- **Automatic Fallback**: `-c:v libx264 -preset superfast -crf 24` (if NVENC/CDI is unavailable on the host)
- **Stream Settings**: Variable framerate (`-vsync 2`), max width 720p (`scale=min(720\,iw):-2`), `yuv420p` pixel format, AAC Mono 128kbps audio (`-c:a aac -ac 1 -b:a 128k`), and `+faststart` MOOV atom placement.

### Connection Resilience
- Configured with separate `HTTPXRequest` connection pools for outbound API calls and long-polling (`getUpdates`), plus a global error handler to prevent stale keep-alive `httpx.ConnectError` drops.

---

## 🚀 Deployment (Dockhand / SputnikX)

The bot is orchestrated on `sputnik` via the `SputnikXCore` repository (`sputnikcore/metahaterbot/compose.yaml`) as Dockhand Git Stack `metahaterbot` (`stackId: 26`):
1. Ensure `TELEGRAM_BOT_TOKEN` is set in the Dockhand stack environment variables.
2. Push updates to `SRINIOLO2/TelegramUtilityBot` (`main`).
3. Redeploy the `metahaterbot` stack in Dockhand with `buildOnDeploy` enabled.
