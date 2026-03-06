from __future__ import annotations

from collections.abc import Callable

from trendbot.collectors import (
    DEFAULT_GITHUB_QUERIES,
    DevToCollector,
    GitHubCollector,
    HackerNewsCollector,
    ProductHuntCollector,
    RedditCollector,
    SubstackCollector,
)
from trendbot.collectors.devto import CollectorError as DevToCollectorError
from trendbot.collectors.github import CollectorError as GitHubCollectorError
from trendbot.collectors.hackernews import CollectorError as HackerNewsCollectorError
from trendbot.collectors.producthunt import CollectorError as ProductHuntCollectorError
from trendbot.collectors.reddit import CollectorError as RedditCollectorError
from trendbot.collectors.substack import CollectorError as SubstackCollectorError
from trendbot.config import Settings
from trendbot.models import Signal
from trendbot.utils import deduplicate_signals, parse_window

SourceResultCallback = Callable[[str, int, str | None], None]


def collect_signals(
    *,
    settings: Settings,
    window: str,
    limit: int,
    github_query: list[str] | None = None,
    github_language: str = "python",
    hn_mode: str = "top",
    reddit_subreddit: list[str] | None = None,
    devto_tag: list[str] | None = None,
    substack_feed: list[str] | None = None,
    on_source_result: SourceResultCallback | None = None,
) -> list[Signal]:
    window_delta = parse_window(window)
    all_signals: list[Signal] = []
    queries = github_query if github_query else DEFAULT_GITHUB_QUERIES

    if settings.github_token:
        github_collector = GitHubCollector(token=settings.github_token)
        try:
            gh_signals = github_collector.collect(
                queries=queries,
                language=github_language,
                sort="stars",
                limit=limit,
                window=window_delta,
            )
            all_signals.extend(gh_signals)
            _emit_source_result(on_source_result, "github", len(gh_signals), None)
        except GitHubCollectorError as exc:
            _emit_source_result(on_source_result, "github", 0, str(exc))
    else:
        _emit_source_result(
            on_source_result,
            "github",
            0,
            "GITHUB_TOKEN not set; skipping GitHub collector.",
        )

    hn_collector = HackerNewsCollector()
    try:
        hn_signals = hn_collector.collect(mode=hn_mode, limit=limit, window=window_delta)
        all_signals.extend(hn_signals)
        _emit_source_result(on_source_result, "hackernews", len(hn_signals), None)
    except HackerNewsCollectorError as exc:
        _emit_source_result(on_source_result, "hackernews", 0, str(exc))

    if settings.producthunt_token:
        ph_collector = ProductHuntCollector(token=settings.producthunt_token)
        try:
            ph_signals = ph_collector.collect(limit=limit, window=window_delta)
            all_signals.extend(ph_signals)
            _emit_source_result(on_source_result, "producthunt", len(ph_signals), None)
        except ProductHuntCollectorError as exc:
            _emit_source_result(on_source_result, "producthunt", 0, str(exc))
    else:
        _emit_source_result(
            on_source_result,
            "producthunt",
            0,
            "PRODUCTHUNT_TOKEN not set; skipping Product Hunt collector.",
        )

    selected_reddit_subreddits = (
        reddit_subreddit if reddit_subreddit else settings.reddit_subreddits
    )
    if (
        settings.reddit_client_id
        and settings.reddit_client_secret
        and selected_reddit_subreddits
    ):
        reddit_collector = RedditCollector(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        try:
            reddit_signals = reddit_collector.collect(
                subreddits=selected_reddit_subreddits,
                limit=limit,
                window=window_delta,
            )
            all_signals.extend(reddit_signals)
            _emit_source_result(on_source_result, "reddit", len(reddit_signals), None)
        except RedditCollectorError as exc:
            _emit_source_result(on_source_result, "reddit", 0, str(exc))
    else:
        _emit_source_result(
            on_source_result,
            "reddit",
            0,
            "Reddit disabled; set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and subreddits.",
        )

    selected_devto_tags = devto_tag if devto_tag else settings.devto_tags
    if selected_devto_tags:
        devto_collector = DevToCollector()
        try:
            devto_signals = devto_collector.collect(
                tags=selected_devto_tags,
                limit=limit,
                window=window_delta,
            )
            all_signals.extend(devto_signals)
            _emit_source_result(on_source_result, "devto", len(devto_signals), None)
        except DevToCollectorError as exc:
            _emit_source_result(on_source_result, "devto", 0, str(exc))
    else:
        _emit_source_result(on_source_result, "devto", 0, "DEVTO_TAGS not set; skipping.")

    selected_substack_feeds = substack_feed if substack_feed else settings.substack_feeds
    if selected_substack_feeds:
        substack_collector = SubstackCollector()
        try:
            substack_signals = substack_collector.collect(
                feed_urls=selected_substack_feeds,
                limit=limit,
                window=window_delta,
            )
            all_signals.extend(substack_signals)
            _emit_source_result(on_source_result, "substack", len(substack_signals), None)
        except SubstackCollectorError as exc:
            _emit_source_result(on_source_result, "substack", 0, str(exc))
    else:
        _emit_source_result(
            on_source_result,
            "substack",
            0,
            "SUBSTACK_FEEDS not set; skipping Substack collector.",
        )

    return deduplicate_signals(all_signals)


def _emit_source_result(
    callback: SourceResultCallback | None,
    source: str,
    count: int,
    error: str | None,
) -> None:
    if callback:
        callback(source, count, error)
