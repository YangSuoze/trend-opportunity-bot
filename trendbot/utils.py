from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import TextIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from trendbot.models import Signal

_WINDOW_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[mhdw])$")
_GITHUB_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/[\w\-\.]+/[\w\-\.]+(?:/[\w\-\./]+)?",
    re.IGNORECASE,
)
_TRACKING_QUERY_PREFIXES = (
    "utm_",
    "ref",
    "source",
    "fbclid",
    "gclid",
)


def parse_window(value: str) -> timedelta:
    match = _WINDOW_PATTERN.match(value.strip().lower())
    if not match:
        raise ValueError("window must match <number><m|h|d|w>, e.g. 24h")

    amount = int(match.group("value"))
    unit = match.group("unit")

    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    return timedelta(weeks=amount)


def normalize_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""

    parsed = urlsplit(value if "://" in value else f"https://{value}")
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()

    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_items = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith(_TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, item_value))
    query_items.sort()
    query = urlencode(query_items, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def build_fingerprint(url: str, title: str) -> str:
    normalized = f"{normalize_url(url)}|{normalize_title(title)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deduplicate_signals(signals: Iterable[Signal]) -> list[Signal]:
    unique: list[Signal] = []
    seen: set[str] = set()
    for signal in signals:
        if signal.fingerprint in seen:
            continue
        seen.add(signal.fingerprint)
        unique.append(signal)
    return unique


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_jsonl_rows(handle: TextIO, items: Iterable[BaseModel | dict]) -> None:
    for item in items:
        if isinstance(item, BaseModel):
            payload = item.model_dump(mode="json")
        else:
            payload = item
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def write_jsonl(path: Path, items: Iterable[BaseModel | dict]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        _write_jsonl_rows(handle, items)


def append_jsonl(path: Path, items: Iterable[BaseModel | dict]) -> None:
    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        _write_jsonl_rows(handle, items)


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def extract_github_urls(text: str) -> list[str]:
    if not text:
        return []

    matches = _GITHUB_URL_PATTERN.findall(text)
    normalized = []
    seen: set[str] = set()
    for match in matches:
        cleaned = normalize_url(match)
        if cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized


def strip_html_tags(raw_html: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", raw_html or "")
    return " ".join(no_tags.split())
