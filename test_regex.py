import re

SOCIAL_LINK_PATTERN = re.compile(
    r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv|share/[^/]+)/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9-_]+'
    r'|https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/video/[0-9]+'
    r'|https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9]+'
    r'|https?://(?:vm|vt|v)\.tiktok\.com/[A-Za-z0-9]+)',
    re.IGNORECASE
)

links = [
    "https://www.tiktok.com/t/ZPR3x2mN/",
    "https://vm.tiktok.com/ZTR3x2mN",
    "https://www.tiktok.com/@zachking/video/6768504823336815877?is_copy_url=1&is_from_webapp=v1",
]

for l in links:
    m = SOCIAL_LINK_PATTERN.search(l)
    print(f"{l}: {m.group(0) if m else 'No match'}")
