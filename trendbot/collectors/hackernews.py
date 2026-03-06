from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trendbot.http import RequestError, request_json
from trendbot.models import Signal
from trendbot.utils import build_fingerprint, extract_github_urls, strip_html_tags


class CollectorError(RuntimeError):
    pass


class HackerNewsCollector:
    base_url = "https://hacker-news.firebaseio.com/v0"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=15.0)

    def collect(
        self,
        *,
        mode: str = "top",
        limit: int = 30,
        window: timedelta | None = None,
    ) -> list[Signal]:
        mode = mode.lower()
        if mode not in {"top", "new", "show"}:
            raise CollectorError("hn mode must be one of: top, new, show")

        now = datetime.now(UTC)
        threshold = now - window if window else None
        ids = self._fetch_story_ids(mode)

        signals: list[Signal] = []
        pool_size = max(limit * 5, limit)

        for story_id in ids[:pool_size]:
            if len(signals) >= limit:
                break

            item = self._fetch_item(story_id)
            if not item or item.get("type") != "story":
                continue

            published_at = datetime.fromtimestamp(item.get("time", 0), tz=UTC)
            if threshold and published_at < threshold:
                continue

            github_urls = self._extract_story_github_urls(item)
            if not github_urls:
                continue

            title = str(item.get("title") or f"HN story {story_id}")
            description = strip_html_tags(str(item.get("text") or ""))

            for github_url in github_urls:
                if len(signals) >= limit:
                    break

                signals.append(
                    Signal(
                        source="hackernews",
                        title=title,
                        url=github_url,
                        description=description,
                        tags=["hackernews", "github"],
                        metrics={
                            "hn_id": item.get("id") or story_id,
                            "score": item.get("score") or 0,
                            "comments": item.get("descendants") or 0,
                        },
                        captured_at=published_at,
                        fingerprint=build_fingerprint(github_url, title),
                    )
                )

        return signals

    def _fetch_story_ids(self, mode: str) -> list[int]:
        url = f"{self.base_url}/{mode}stories.json"
        try:
            payload = request_json(self.client, "GET", url, retries=3, backoff_seconds=0.75)
        except RequestError as exc:
            raise CollectorError(f"failed fetching Hacker News {mode} story ids: {exc}") from exc

        if not isinstance(payload, list):
            raise CollectorError("unexpected Hacker News id response shape")

        return [int(item) for item in payload]

    def _fetch_item(self, item_id: int) -> dict | None:
        url = f"{self.base_url}/item/{item_id}.json"
        try:
            payload = request_json(self.client, "GET", url, retries=3, backoff_seconds=0.75)
        except RequestError:
            return None

        if isinstance(payload, dict):
            return payload
        return None

    def _extract_story_github_urls(self, item: dict) -> list[str]:
        candidates: list[str] = []
        url_value = str(item.get("url") or "")
        text_value = str(item.get("text") or "")

        candidates.extend(extract_github_urls(url_value))
        candidates.extend(extract_github_urls(text_value))

        seen: set[str] = set()
        deduped: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped
