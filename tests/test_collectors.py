from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from trendbot.collectors.github import GitHubCollector
from trendbot.collectors.hackernews import HackerNewsCollector
from trendbot.collectors.producthunt import ProductHuntCollector


def test_github_collector_collects_graphql_nodes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.github.com/graphql")
        body = json.loads(request.content.decode("utf-8"))
        assert "variables" in body
        payload = {
            "data": {
                "search": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "nameWithOwner": "acme/repo-a",
                            "description": "A",
                            "url": "https://github.com/acme/repo-a",
                            "stargazerCount": 123,
                            "forkCount": 5,
                            "watchers": {"totalCount": 10},
                            "primaryLanguage": {"name": "Python"},
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2026-03-06T00:00:00Z",
                        },
                        {
                            "nameWithOwner": "acme/repo-b",
                            "description": "B",
                            "url": "https://github.com/acme/repo-b",
                            "stargazerCount": 50,
                            "forkCount": 1,
                            "watchers": {"totalCount": 2},
                            "primaryLanguage": {"name": "Python"},
                            "createdAt": "2025-01-01T00:00:00Z",
                            "updatedAt": "2026-03-06T00:00:00Z",
                        },
                    ],
                }
            }
        }
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = GitHubCollector(token="token", client=client)

    signals = collector.collect(queries=["rag"], language="python", limit=2)

    assert len(signals) == 2
    assert signals[0].source == "github"
    assert signals[0].metrics["stargazer_count"] == 123


def test_hackernews_collector_extracts_github_urls() -> None:
    now = int(datetime.now(UTC).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/topstories.json"):
            return httpx.Response(200, json=[111, 222])
        if path.endswith("/item/111.json"):
            return httpx.Response(
                200,
                json={
                    "id": 111,
                    "type": "story",
                    "title": "A cool repo",
                    "url": "https://github.com/acme/repo-a",
                    "score": 42,
                    "descendants": 8,
                    "time": now,
                },
            )
        if path.endswith("/item/222.json"):
            return httpx.Response(
                200,
                json={
                    "id": 222,
                    "type": "story",
                    "title": "Another",
                    "text": '<a href="https://github.com/acme/repo-b">repo</a>',
                    "score": 10,
                    "descendants": 2,
                    "time": now,
                },
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = HackerNewsCollector(client=client)

    signals = collector.collect(mode="top", limit=5)

    assert len(signals) == 2
    assert signals[0].source == "hackernews"
    assert signals[0].url.startswith("https://github.com/")


def test_producthunt_collector_collects_today_posts() -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.producthunt.com/v2/api/graphql")
        return httpx.Response(
            200,
            json={
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "id": "1",
                                    "name": "Launch X",
                                    "tagline": "Fast prototyping",
                                    "description": "Build AI MVPs quickly",
                                    "url": "https://www.producthunt.com/posts/launch-x",
                                    "votesCount": 100,
                                    "commentsCount": 9,
                                    "createdAt": now,
                                }
                            }
                        ]
                    }
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = ProductHuntCollector(token="ph", client=client)

    signals = collector.collect(limit=10)

    assert len(signals) == 1
    assert signals[0].source == "producthunt"
    assert signals[0].metrics["votes_count"] == 100
