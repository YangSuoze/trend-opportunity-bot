from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trendbot.http import RequestError, request_json
from trendbot.models import Signal
from trendbot.utils import build_fingerprint

DEFAULT_GITHUB_QUERIES: list[str] = [
    "rag orchestration agent framework",
    "python retrieval augmented generation",
    "growth analytics automation ai",
]

_GITHUB_GRAPHQL_QUERY = """
query SearchRepositories($query: String!, $first: Int!, $after: String) {
  search(type: REPOSITORY, query: $query, first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on Repository {
        nameWithOwner
        description
        url
        stargazerCount
        forkCount
        watchers {
          totalCount
        }
        primaryLanguage {
          name
        }
        createdAt
        updatedAt
      }
    }
  }
}
"""


class CollectorError(RuntimeError):
    pass


class GitHubCollector:
    endpoint = "https://api.github.com/graphql"

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token.strip()
        self.client = client or httpx.Client(timeout=20.0)

    def collect(
        self,
        *,
        queries: Iterable[str],
        language: str | None = "python",
        sort: str = "stars",
        limit: int = 30,
        window: timedelta | None = None,
    ) -> list[Signal]:
        if not self.token:
            return []

        now = datetime.now(UTC)
        threshold = now - window if window else None

        signals: list[Signal] = []

        for raw_query in queries:
            if not raw_query.strip():
                continue
            built_query = self._build_search_query(raw_query, language=language, sort=sort)
            repos = self._search_repositories(built_query, limit=limit)
            for repo in repos:
                updated_at = _parse_github_time(repo.get("updatedAt"))
                if threshold and updated_at and updated_at < threshold:
                    continue

                language_name = (repo.get("primaryLanguage") or {}).get("name")
                tags = ["github"]
                if language_name:
                    tags.append(language_name.lower())

                url = str(repo.get("url", ""))
                title = str(repo.get("nameWithOwner", ""))

                signals.append(
                    Signal(
                        source="github",
                        title=title,
                        url=url,
                        description=str(repo.get("description") or ""),
                        tags=tags,
                        metrics={
                            "stargazer_count": repo.get("stargazerCount") or 0,
                            "fork_count": repo.get("forkCount") or 0,
                            "watcher_count": ((repo.get("watchers") or {}).get("totalCount") or 0),
                        },
                        captured_at=updated_at or now,
                        fingerprint=build_fingerprint(url, title),
                    )
                )

        return signals

    def _build_search_query(self, query: str, *, language: str | None, sort: str) -> str:
        result = query.strip()
        if language:
            result = f"{result} language:{language.strip()}"
        if sort == "stars":
            result = f"{result} sort:stars-desc"
        return result

    def _search_repositories(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

        repositories: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(repositories) < limit:
            page_size = min(100, limit - len(repositories))
            payload = {
                "query": _GITHUB_GRAPHQL_QUERY,
                "variables": {
                    "query": query,
                    "first": page_size,
                    "after": cursor,
                },
            }

            try:
                result = request_json(
                    self.client,
                    "POST",
                    self.endpoint,
                    headers=headers,
                    json_body=payload,
                    retries=4,
                    backoff_seconds=1.0,
                )
            except RequestError as exc:
                raise CollectorError(f"GitHub request failed: {exc}") from exc

            errors = result.get("errors") or []
            if errors:
                messages = "; ".join(
                    str(error.get("message", "unknown GraphQL error")) for error in errors
                )
                raise CollectorError(f"GitHub GraphQL error: {messages}")

            search_result = ((result.get("data") or {}).get("search") or {})
            nodes = search_result.get("nodes") or []
            repositories.extend(
                node for node in nodes if isinstance(node, dict) and node.get("url")
            )

            page_info = search_result.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        return repositories[:limit]


def _parse_github_time(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None
