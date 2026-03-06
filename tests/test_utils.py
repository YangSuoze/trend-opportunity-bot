from __future__ import annotations

from datetime import UTC, datetime

from trendbot.models import Signal
from trendbot.utils import (
    build_fingerprint,
    deduplicate_signals,
    normalize_url,
    parse_window,
)


def test_parse_window_hours() -> None:
    assert parse_window("24h").total_seconds() == 24 * 3600


def test_parse_window_days() -> None:
    assert parse_window("7d").total_seconds() == 7 * 24 * 3600


def test_normalize_url_removes_tracking_and_fragment() -> None:
    result = normalize_url("https://GitHub.com/openai/openai-python/?utm_source=x&b=1#readme")
    assert result == "https://github.com/openai/openai-python?b=1"


def test_fingerprint_is_stable_for_url_and_title_variants() -> None:
    a = build_fingerprint("https://github.com/openai/openai-python/", "  Cool Repo ")
    b = build_fingerprint("https://github.com/openai/openai-python", "cool   repo")
    assert a == b


def test_deduplicate_signals_by_fingerprint() -> None:
    fp = build_fingerprint("https://example.com/x", "X")
    first = Signal(
        source="x",
        title="X",
        url="https://example.com/x",
        description="",
        tags=[],
        metrics={},
        captured_at=datetime.now(UTC),
        fingerprint=fp,
    )
    second = Signal(
        source="y",
        title="X",
        url="https://example.com/x",
        description="",
        tags=[],
        metrics={},
        captured_at=datetime.now(UTC),
        fingerprint=fp,
    )

    deduped = deduplicate_signals([first, second])
    assert len(deduped) == 1
    assert deduped[0].source == "x"
