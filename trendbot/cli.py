from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from trendbot.analyzer import AnalyzeError, analyze_file
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
from trendbot.openai_client import OpenAIClient, OpenAIClientError
from trendbot.reporting import report_from_file
from trendbot.utils import deduplicate_signals, parse_window, write_jsonl

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()
error_console = Console(stderr=True)


@app.command()
def collect(
    window: Annotated[
        str,
        typer.Option("--window", help="Collection window, e.g. 24h, 7d"),
    ] = "24h",
    out: Annotated[
        Path,
        typer.Option("--out", help="Output JSONL path for normalized signals"),
    ] = ...,
    github_query: Annotated[
        list[str] | None,
        typer.Option("--github-query", help="Custom GitHub search query (repeatable)"),
    ] = None,
    github_language: Annotated[
        str,
        typer.Option("--github-language", help="GitHub language qualifier"),
    ] = "python",
    hn_mode: Annotated[
        str,
        typer.Option("--hn-mode", help="Hacker News mode: top|new|show"),
    ] = "top",
    reddit_subreddit: Annotated[
        list[str] | None,
        typer.Option(
            "--reddit-subreddit",
            help="Reddit subreddit (repeatable, requires REDDIT_CLIENT_ID/SECRET)",
        ),
    ] = None,
    devto_tag: Annotated[
        list[str] | None,
        typer.Option("--devto-tag", help="DEV.to tag (repeatable)"),
    ] = None,
    substack_feed: Annotated[
        list[str] | None,
        typer.Option("--substack-feed", help="Substack RSS feed URL (repeatable)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Max signals per source"),
    ] = 30,
) -> None:
    """Collect trend signals from available sources and optional API/RSS collectors."""

    settings = Settings.load()
    try:
        window_delta = parse_window(window)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--window") from exc

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
            console.print(f"[green]GitHub:[/green] collected {len(gh_signals)} signals")
        except GitHubCollectorError as exc:
            console.print(f"[yellow]GitHub collector failed:[/yellow] {exc}")
    else:
        console.print("[yellow]GITHUB_TOKEN not set; skipping GitHub collector.[/yellow]")

    hn_collector = HackerNewsCollector()
    try:
        hn_signals = hn_collector.collect(mode=hn_mode, limit=limit, window=window_delta)
        all_signals.extend(hn_signals)
        console.print(f"[green]Hacker News:[/green] collected {len(hn_signals)} signals")
    except HackerNewsCollectorError as exc:
        console.print(f"[yellow]Hacker News collector failed:[/yellow] {exc}")

    if settings.producthunt_token:
        ph_collector = ProductHuntCollector(token=settings.producthunt_token)
        try:
            ph_signals = ph_collector.collect(limit=limit, window=window_delta)
            all_signals.extend(ph_signals)
            console.print(f"[green]Product Hunt:[/green] collected {len(ph_signals)} signals")
        except ProductHuntCollectorError as exc:
            console.print(f"[yellow]Product Hunt collector failed:[/yellow] {exc}")
    else:
        console.print(
            "[yellow]PRODUCTHUNT_TOKEN not set; skipping Product Hunt collector.[/yellow]"
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
            console.print(f"[green]Reddit:[/green] collected {len(reddit_signals)} signals")
        except RedditCollectorError as exc:
            console.print(f"[yellow]Reddit collector failed:[/yellow] {exc}")
    else:
        console.print(
            "[yellow]Reddit disabled; set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, "
            "and REDDIT_SUBREDDITS (or --reddit-subreddit).[/yellow]"
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
            console.print(f"[green]DEV.to:[/green] collected {len(devto_signals)} signals")
        except DevToCollectorError as exc:
            console.print(f"[yellow]DEV.to collector failed:[/yellow] {exc}")
    else:
        console.print("[yellow]DEVTO_TAGS not set; skipping DEV.to collector.[/yellow]")

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
            console.print(f"[green]Substack:[/green] collected {len(substack_signals)} signals")
        except SubstackCollectorError as exc:
            console.print(f"[yellow]Substack collector failed:[/yellow] {exc}")
    else:
        console.print("[yellow]SUBSTACK_FEEDS not set; skipping Substack collector.[/yellow]")

    unique_signals = deduplicate_signals(all_signals)
    write_jsonl(out, unique_signals)

    console.print(f"[bold]Saved {len(unique_signals)} deduplicated signals to {out}[/bold]")


@app.command()
def analyze(
    in_path: Annotated[
        Path,
        typer.Option(
            "--in",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Input signals JSONL path",
        ),
    ] = ...,
    out: Annotated[
        Path,
        typer.Option("--out", help="Output JSONL path for opportunity cards"),
    ] = ...,
    top: Annotated[
        int,
        typer.Option("--top", min=1, max=500, help="Analyze top N ranked signals"),
    ] = 30,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--no-resume",
            help="Resume from existing output file and skip already analyzed fingerprints",
        ),
    ] = True,
) -> None:
    """Analyze signals with an OpenAI-compatible model and generate opportunity cards."""

    settings = Settings.load()
    if not settings.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is required for analyze command")

    client = OpenAIClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    try:
        cards = analyze_file(
            input_path=in_path,
            output_path=out,
            top=top,
            client=client,
            resume=resume,
            on_progress=lambda index, total, signal: console.print(
                f"[{index}/{total}] analyzing {signal.title} (source={signal.source})"
            ),
            on_error=lambda signal, exc: error_console.print(
                "[yellow]analysis failed:[/yellow] "
                f"{signal.title} (source={signal.source}) -> {exc}"
            ),
        )
    except (AnalyzeError, OpenAIClientError, ValueError) as exc:
        raise typer.Exit(code=_exit_with_error(str(exc))) from exc

    console.print(f"[bold]Saved {len(cards)} new opportunity cards to {out}[/bold]")


@app.command()
def report(
    in_path: Annotated[
        Path,
        typer.Option(
            "--in",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Input opportunities JSONL path",
        ),
    ] = ...,
    out: Annotated[
        Path,
        typer.Option("--out", help="Output markdown report path"),
    ] = ...,
) -> None:
    """Generate a ranked markdown report from opportunity cards JSONL."""

    markdown = report_from_file(in_path, out)
    console.print(f"[bold]Saved report ({len(markdown)} bytes) to {out}[/bold]")


def _exit_with_error(message: str) -> int:
    console.print(f"[red]{message}[/red]")
    return 1


if __name__ == "__main__":
    app()
