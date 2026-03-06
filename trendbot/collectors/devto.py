from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trendbot.http import RequestError, request_json
from trendbot.models import Signal
from trendbot.utils import build_fingerprint

DEFAULT_DEVTO_TAGS: list[str] = [
    "buildinpublic",
    "saas",
    "startup",
]


class CollectorError(RuntimeError):
    pass


class DevToCollector:
    endpoint = "https://dev.to/api/articles"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20.0)

    def collect(
        self,
        *,
        tags: Iterable[str],
        limit: int = 30,
        window: timedelta | None = None,
    ) -> list[Signal]:
        selected_tags = _clean_values(tags)
        if not selected_tags:
            return []

        now = datetime.now(UTC)
        threshold = now - window if window else None
        page_size = min(max(limit * 2, 20), 100)

        signals: list[Signal] = []
        seen: set[str] = set()

        for tag in selected_tags:
            posts = self._fetch_tag_posts(tag=tag, per_page=page_size)
            for post in posts:
                if len(signals) >= limit:
                    break
                if not isinstance(post, dict):
                    continue

                title = str(post.get("title") or "DEV Article")
                url = str(post.get("url") or "").strip()
                if not url:
                    continue

                captured_at = (
                    _parse_time(post.get("published_at"))
                    or _parse_time(post.get("created_at"))
                    or now
                )
                if threshold and captured_at < threshold:
                    continue

                fingerprint = build_fingerprint(url, title)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                signal_tags = ["devto", *_normalize_tags(post.get("tag_list"))]

                signals.append(
                    Signal(
                        source="devto",
                        title=title,
                        url=url,
                        description=str(post.get("description") or ""),
                        tags=signal_tags,
                        metrics={
                            "reactions": post.get("positive_reactions_count")
                            or post.get("public_reactions_count")
                            or 0,
                            "comments": post.get("comments_count") or 0,
                            "page_views": post.get("page_views_count"),
                        },
                        captured_at=captured_at,
                        fingerprint=fingerprint,
                    )
                )

            if len(signals) >= limit:
                break

        return signals

    def _fetch_tag_posts(self, *, tag: str, per_page: int) -> list[dict[str, Any]]:
        params = {
            "tag": tag,
            "per_page": per_page,
        }

        try:
            payload = request_json(
                self.client,
                "GET",
                self.endpoint,
                params=params,
                retries=3,
                backoff_seconds=0.75,
            )
        except RequestError as exc:
            raise CollectorError(f"DEV.to request failed for tag={tag}: {exc}") from exc

        if not isinstance(payload, list):
            raise CollectorError("unexpected DEV.to response shape")

        return [item for item in payload if isinstance(item, dict)]


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        tags = [str(tag).strip().lower() for tag in value if str(tag).strip()]
    elif isinstance(value, str):
        tags = [part.strip().lower() for part in value.split(",") if part.strip()]
    else:
        tags = []
    return _clean_values(tags)


def _clean_values(values: Iterable[str]) -> list[str]:
    cleaned_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_values.append(cleaned)
    return cleaned_values
