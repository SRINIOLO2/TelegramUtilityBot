import hashlib
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Union


class MediaCache:
    """
    Bounded LRU cache for storing social URLs, uploaded Telegram file_ids,
    post captions, and recent per-user links for inline queries.
    """

    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self._urls: OrderedDict[str, str] = OrderedDict()
        self._media_files: OrderedDict[str, List[Tuple[str, str]]] = OrderedDict()
        self._captions: OrderedDict[str, str] = OrderedDict()
        self._recent_user_links: Dict[int, List[str]] = {}

    @staticmethod
    def hash_url(url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]

    def _set_bounded(self, store: OrderedDict, key: str, value) -> None:
        if key in store:
            store.move_to_end(key)
        store[key] = value
        while len(store) > self.max_entries:
            store.popitem(last=False)

    def store_url(self, url: str) -> str:
        url_hash = self.hash_url(url)
        self._set_bounded(self._urls, url_hash, url)
        return url_hash

    def bind_message(self, message_id: Union[int, str], url: str) -> None:
        self._set_bounded(self._urls, str(message_id), url)

    def get_url(self, key: str) -> Optional[str]:
        val = self._urls.get(str(key))
        if val is not None:
            self._urls.move_to_end(str(key))
        return val

    def store_media_files(
        self,
        url_hash: str,
        items: List[Tuple[str, str]],
        caption: Optional[str] = None,
    ) -> None:
        self._set_bounded(self._media_files, url_hash, list(items))
        if caption:
            self._set_bounded(self._captions, url_hash, caption)

    def get_media_files(self, url_hash: str) -> Optional[List[Tuple[str, str]]]:
        val = self._media_files.get(url_hash)
        if val is not None:
            self._media_files.move_to_end(url_hash)
        return val

    def get_caption(self, url_hash: str) -> Optional[str]:
        return self._captions.get(url_hash)

    def save_user_link(self, user_id: int, url: str) -> None:
        links = self._recent_user_links.setdefault(user_id, [])
        if url in links:
            links.remove(url)
        links.insert(0, url)
        self._recent_user_links[user_id] = links[:5]

    def get_user_links(self, user_id: int) -> List[str]:
        return list(self._recent_user_links.get(user_id, []))

    # Dict-compatible helpers for backward compatibility with url_cache[key]
    def __setitem__(self, key: str, value: str) -> None:
        self._set_bounded(self._urls, str(key), value)

    def __getitem__(self, key: str) -> str:
        return self._urls[str(key)]

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.get_url(str(key)) or default
