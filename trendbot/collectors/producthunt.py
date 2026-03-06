from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trendbot.http import RequestError, request_json
from trendbot.models import Signal
from trendbot.utils import build_fingerprint


class CollectorError(RuntimeError):
    pass


_PRODUCTHUNT_POSTS_QUERY = """
query FetchPosts($first: Int!) {
  posts(first: $first) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        createdAt
      }
    }
  }
}
"""


class ProductHuntCollector:
    endpoint = "https://api.producthunt.com/v2/api/graphql"

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token.strip()
        self.client = client or httpx.Client(timeout=20.0)

    def collect(self, *, limit: int = 30, window: timedelta | None = None) -> list[Signal]:
        if not self.token:
            return []

        now = datetime.now(UTC)
        threshold = (
            now - window
            if window
            else datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        )

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        payload = {
            "query": _PRODUCTHUNT_POSTS_QUERY,
            "variables": {"first": max(limit * 2, 20)},
        }

        try:
            response = request_json(
                self.client,
                "POST",
                self.endpoint,
                headers=headers,
                json_body=payload,
                retries=3,
                backoff_seconds=1.0,
            )
        except RequestError as exc:
            raise CollectorError(f"Product Hunt request failed: {exc}") from exc

        errors = response.get("errors") or []
        if errors:
            messages = "; ".join(
                str(error.get("message", "unknown GraphQL error")) for error in errors
            )
            raise CollectorError(f"Product Hunt GraphQL error: {messages}")

        edges = (((response.get("data") or {}).get("posts") or {}).get("edges") or [])
        signals: list[Signal] = []

        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue

            created_at = _parse_time(node.get("createdAt")) or now
            if created_at < threshold:
                continue

            title = str(node.get("name") or "Product Hunt Post")
            url = str(node.get("url") or "")
            if not url:
                continue

            description_parts = [
                str(node.get("tagline") or "").strip(),
                str(node.get("description") or "").strip(),
            ]
            description = " - ".join(part for part in description_parts if part)

            signals.append(
                Signal(
                    source="producthunt",
                    title=title,
                    url=url,
                    description=description,
                    tags=["producthunt"],
                    metrics={
                        "votes_count": node.get("votesCount") or 0,
                        "comments": node.get("commentsCount") or 0,
                    },
                    captured_at=created_at,
                    fingerprint=build_fingerprint(url, title),
                )
            )

            if len(signals) >= limit:
                break

        return signals


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
