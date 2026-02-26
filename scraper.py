from __future__ import annotations

import json
import re
from typing import Any, Iterator

from scrapling.fetchers import Fetcher


class TikTokScrapeError(Exception):
    """Raised when TikTok profile data cannot be extracted."""


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _extract_payload(page: Any) -> dict[str, Any]:
    selectors = (
        "script#__UNIVERSAL_DATA_FOR_REHYDRATION__::text",
        "script#SIGI_STATE::text",
        "script#__NEXT_DATA__::text",
    )
    for selector in selectors:
        raw_payload = page.css(selector).get()
        if not raw_payload:
            continue
        try:
            loaded = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    raise TikTokScrapeError("Could not read TikTok profile payload from page.")


def _extract_user_and_stats(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    for candidate in _walk(payload):
        user_info = candidate.get("userInfo")
        if isinstance(user_info, dict):
            user = user_info.get("user", {})
            stats = user_info.get("stats", {})
            if isinstance(user, dict) and user.get("uniqueId"):
                return user, stats if isinstance(stats, dict) else {}

        user = candidate.get("user")
        stats = candidate.get("stats")
        if isinstance(user, dict) and user.get("uniqueId") and isinstance(stats, dict):
            return user, stats

    raise TikTokScrapeError("Could not find TikTok account details in payload.")


def _extract_recent_videos(payload: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    for candidate in _walk(payload):
        item_module = candidate.get("itemModule")
        if not isinstance(item_module, dict) or not item_module:
            continue
        videos: list[dict[str, Any]] = []
        for item in item_module.values():
            if not isinstance(item, dict):
                continue
            stats = item.get("stats", {})
            if not isinstance(stats, dict):
                stats = {}
            videos.append(
                {
                    "id": item.get("id"),
                    "description": item.get("desc", ""),
                    "play_count": stats.get("playCount"),
                    "digg_count": stats.get("diggCount"),
                    "comment_count": stats.get("commentCount"),
                    "share_count": stats.get("shareCount"),
                }
            )
        if videos:
            return videos[:limit]
    return []


def normalize_username(username: str) -> str:
    normalized = username.strip().lstrip("@").lower()
    if not re.fullmatch(r"[A-Za-z0-9._]{2,24}", normalized):
        raise TikTokScrapeError("Please enter a valid TikTok username.")
    return normalized


def fetch_tiktok_profile(username: str) -> dict[str, Any]:
    normalized = normalize_username(username)
    page = Fetcher.get(f"https://www.tiktok.com/@{normalized}")
    payload = _extract_payload(page)
    user, stats = _extract_user_and_stats(payload)

    return {
        "username": user.get("uniqueId", normalized),
        "nickname": user.get("nickname"),
        "bio": user.get("signature"),
        "verified": bool(user.get("verified")),
        "followers": stats.get("followerCount"),
        "following": stats.get("followingCount"),
        "likes": stats.get("heartCount"),
        "videos_count": stats.get("videoCount"),
        "profile_url": f"https://www.tiktok.com/@{normalized}",
        "recent_videos": _extract_recent_videos(payload),
    }
