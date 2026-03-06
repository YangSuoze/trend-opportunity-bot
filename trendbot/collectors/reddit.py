from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trendbot.http import RequestError, request_json
from trendbot.models import Signal
from trendbot.utils import build_fingerprint

DEFAULT_REDDIT_SUBREDDITS: list[str] = [
    "SideProject",
    "startups",
    "selfhosted",
]


class CollectorError(RuntimeError):
    pass


class RedditCollector:
    token_url = "https://www.reddit.com/api/v1/access_token"
    api_base_url = "https://oauth.reddit.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.user_agent = (
            user_agent.strip() or "python:trend-opportunity-bot:v0.1.0 (by /u/unknown)"
        )
        self.client = client or httpx.Client(timeout=20.0)

    def collect(
        self,
        *,
        subreddits: Iterable[str],
        limit: int = 30,
        window: timedelta | None = None,
    ) -> list[Signal]:
        if not self.client_id or not self.client_secret:
            return []

        selected_subreddits = _clean_values(subreddits)
        if not selected_subreddits:
            return []

        token = self._fetch_access_token()
        now = datetime.now(UTC)
        threshold = now - window if window else None
        pool_size = min(max(limit * 3, limit), 100)

        signals: list[Signal] = []
        seen: set[str] = set()

        for subreddit in selected_subreddits:
            stories = self._fetch_subreddit_posts(token=token, subreddit=subreddit, limit=pool_size)
            for story in stories:
                if len(signals) >= limit:
                    break

                data = story.get("data") if isinstance(story, dict) else None
                if not isinstance(data, dict):
                    continue

                title = str(data.get("title") or f"r/{subreddit}")
                url = _extract_post_url(data)
                if not url:
                    continue

                captured_at = _parse_unix_time(data.get("created_utc")) or now
                if threshold and captured_at < threshold:
                    continue

                fingerprint = build_fingerprint(url, title)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                normalized_subreddit = str(data.get("subreddit") or subreddit).strip().lower()
                tags = ["reddit"]
                if normalized_subreddit:
                    tags.append(f"r/{normalized_subreddit}")

                signals.append(
                    Signal(
                        source="reddit",
                        title=title,
                        url=url,
                        description=str(data.get("selftext") or ""),
                        tags=tags,
                        metrics={
                            "score": data.get("score") or 0,
                            "comments": data.get("num_comments") or 0,
                            "upvote_ratio": data.get("upvote_ratio"),
                            "subreddit": str(data.get("subreddit") or subreddit),
                        },
                        captured_at=captured_at,
                        fingerprint=fingerprint,
                    )
                )

            if len(signals) >= limit:
                break

        return signals

    def _fetch_access_token(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}".encode()
        encoded_credentials = base64.b64encode(credentials).decode("ascii")

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = request_json(
                self.client,
                "POST",
                self.token_url,
                headers=headers,
                form_body={"grant_type": "client_credentials"},
                retries=3,
                backoff_seconds=1.0,
            )
        except RequestError as exc:
            raise CollectorError(f"Reddit OAuth request failed: {exc}") from exc

        token = str(response.get("access_token") or "").strip()
        if not token:
            raise CollectorError("Reddit OAuth response missing access_token")
        return token

    def _fetch_subreddit_posts(
        self,
        *,
        token: str,
        subreddit: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        url = f"{self.api_base_url}/r/{subreddit}/new"
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        params = {
            "limit": limit,
            "raw_json": 1,
        }

        try:
            payload = request_json(
                self.client,
                "GET",
                url,
                headers=headers,
                params=params,
                retries=3,
                backoff_seconds=0.75,
            )
        except RequestError as exc:
            raise CollectorError(f"failed fetching r/{subreddit} feed: {exc}") from exc

        children = ((payload.get("data") or {}).get("children") or [])
        if not isinstance(children, list):
            raise CollectorError(f"unexpected Reddit response shape for r/{subreddit}")
        return [item for item in children if isinstance(item, dict)]


def _clean_values(values: Iterable[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(cleaned)
    return selected


def _parse_unix_time(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _extract_post_url(data: dict[str, Any]) -> str:
    url = str(data.get("url_overridden_by_dest") or data.get("url") or "").strip()
    if url:
        return url

    permalink = str(data.get("permalink") or "").strip()
    if permalink.startswith("/"):
        return f"https://www.reddit.com{permalink}"
    return permalink
