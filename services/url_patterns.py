import re
from urllib.parse import urlparse

INSTAGRAM_PATTERN = re.compile(
    r"(https?://(?:www\.)?instagram\.com/(?:[A-Za-z0-9._]+/)?(?:p|reel|reels|tv)/[A-Za-z0-9-_]+"
    r"|https?://(?:www\.)?instagram\.com/share/(?:(?:p|reel|reels|tv)/)?[A-Za-z0-9-_]+"
    r"|https?://(?:www\.)?instagram\.com/stories/[A-Za-z0-9._]+/[0-9]+"
    r"|https?://instagr\.am/p/[A-Za-z0-9-_]+)",
    re.IGNORECASE,
)

TIKTOK_PATTERN = re.compile(
    r"(https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/(?:video|photo)/[0-9]+"
    r"|https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9_-]+"
    r"|https?://(?:vm|vt|v|m)\.tiktok\.com/(?:v/)?[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

FACEBOOK_PATTERN = re.compile(
    r"(https?://(?:(?:www|m|web)\.)?facebook\.com/reel/[0-9A-Za-z._-]+"
    r"|https?://(?:(?:www|m|web)\.)?facebook\.com/watch/?\?[^\s\"'<>]*v=[0-9A-Za-z._-]+"
    r"|https?://(?:(?:www|m|web)\.)?facebook\.com/share/(?:(?:r|v|p)/)?[0-9A-Za-z._-]+"
    r"|https?://(?:(?:www|m|web)\.)?facebook\.com/[A-Za-z0-9._-]+/videos/(?:[A-Za-z0-9._-]+/)?[0-9]+"
    r"|https?://fb\.watch/[0-9A-Za-z._-]+/?)",
    re.IGNORECASE,
)

YOUTUBE_LINK_PATTERN = re.compile(
    r"(https?://(?:(?:www|m)\.)?youtube\.com/(?:watch\?[^\s\"'<>]*v=|shorts/|live/)[A-Za-z0-9_-]+"
    r"|https?://youtu\.be/[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

AUTO_LINK_PATTERN = re.compile(
    f"{INSTAGRAM_PATTERN.pattern}|{TIKTOK_PATTERN.pattern}|{FACEBOOK_PATTERN.pattern}",
    re.IGNORECASE,
)

SOCIAL_LINK_PATTERN = re.compile(
    f"{AUTO_LINK_PATTERN.pattern}|{YOUTUBE_LINK_PATTERN.pattern}",
    re.IGNORECASE,
)

ALLOWED_DOMAINS = (
    "instagram.com",
    "instagr.am",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
    "youtube.com",
    "youtu.be",
)


def get_platform_label(url: str) -> str:
    lower = url.lower()
    if "instagram.com" in lower or "instagr.am" in lower:
        return "Instagram"
    if "tiktok.com" in lower:
        return "TikTok"
    if "facebook.com" in lower or "fb.watch" in lower:
        return "Facebook"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "YouTube"
    return "Media"


def is_safe_social_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        return any(host == d or host.endswith(f".{d}") for d in ALLOWED_DOMAINS)
    except Exception:
        return False
