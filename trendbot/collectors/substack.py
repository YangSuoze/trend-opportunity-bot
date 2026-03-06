from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from trendbot.http import RequestError, request_with_retries
from trendbot.models import Signal
from trendbot.utils import build_fingerprint, strip_html_tags


class CollectorError(RuntimeError):
    pass


class SubstackCollector:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20.0)

    def collect(
        self,
        *,
        feed_urls: Iterable[str],
        limit: int = 30,
        window: timedelta | None = None,
    ) -> list[Signal]:
        selected_feed_urls = _clean_values(feed_urls)
        if not selected_feed_urls:
            return []

        now = datetime.now(UTC)
        threshold = now - window if window else None
        pool_size = max(limit * 3, limit)

        signals: list[Signal] = []
        seen: set[str] = set()

        for feed_url in selected_feed_urls:
            feed = self._fetch_feed(feed_url)
            feed_tag = _feed_tag(feed_url)

            for item in feed.get("items", [])[:pool_size]:
                if len(signals) >= limit:
                    break
                if not isinstance(item, dict):
                    continue

                title = str(item.get("title") or "").strip()
                url = str(item.get("link") or "").strip()
                if not title or not url:
                    continue

                captured_at = _parse_time(item.get("published_at")) or now
                if threshold and captured_at < threshold:
                    continue

                fingerprint = build_fingerprint(url, title)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                tags = ["substack"]
                if feed_tag:
                    tags.append(feed_tag)

                signals.append(
                    Signal(
                        source="substack",
                        title=title,
                        url=url,
                        description=strip_html_tags(str(item.get("description") or "")),
                        tags=tags,
                        metrics={
                            "feed_url": feed_url,
                        },
                        captured_at=captured_at,
                        fingerprint=fingerprint,
                    )
                )

            if len(signals) >= limit:
                break

        return signals

    def _fetch_feed(self, feed_url: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            "User-Agent": "trend-opportunity-bot/0.1",
        }

        try:
            response = request_with_retries(
                self.client,
                "GET",
                feed_url,
                headers=headers,
                retries=3,
                backoff_seconds=1.0,
            )
        except RequestError as exc:
            raise CollectorError(f"Substack feed request failed for {feed_url}: {exc}") from exc

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise CollectorError(f"invalid RSS feed response for {feed_url}") from exc

        return _parse_feed(root)


def _parse_feed(root: ElementTree.Element) -> dict[str, Any]:
    channel = root.find("channel")
    if channel is not None:
        return {
            "channel_title": _find_text(channel, "title"),
            "items": _parse_rss_items(channel.findall("item")),
        }

    atom_ns = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{atom_ns}entry")
    return {
        "channel_title": _find_text(root, f"{atom_ns}title"),
        "items": _parse_atom_entries(entries),
    }


def _parse_rss_items(items: list[ElementTree.Element]) -> list[dict[str, str]]:
    content_ns = "{http://purl.org/rss/1.0/modules/content/}encoded"
    parsed: list[dict[str, str]] = []
    for item in items:
        description = _find_text(item, "description") or _find_text(item, content_ns)
        parsed.append(
            {
                "title": _find_text(item, "title"),
                "link": _find_text(item, "link"),
                "description": description,
                "published_at": _find_text(item, "pubDate"),
            }
        )
    return parsed


def _parse_atom_entries(entries: list[ElementTree.Element]) -> list[dict[str, str]]:
    atom_ns = "{http://www.w3.org/2005/Atom}"
    parsed: list[dict[str, str]] = []
    for entry in entries:
        link = ""
        for link_node in entry.findall(f"{atom_ns}link"):
            href = str(link_node.attrib.get("href") or "").strip()
            if href:
                link = href
                break
        parsed.append(
            {
                "title": _find_text(entry, f"{atom_ns}title"),
                "link": link,
                "description": _find_text(entry, f"{atom_ns}summary"),
                "published_at": _find_text(entry, f"{atom_ns}updated"),
            }
        )
    return parsed


def _find_text(node: ElementTree.Element, tag: str) -> str:
    found = node.find(tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None

    iso_candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _feed_tag(feed_url: str) -> str:
    hostname = urlsplit(feed_url).hostname or ""
    if not hostname:
        return ""
    if hostname.endswith(".substack.com"):
        return hostname.removesuffix(".substack.com")
    return hostname


def _clean_values(values: Iterable[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        selected.append(cleaned)
    return selected
