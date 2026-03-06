from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from trendbot.analyzer import AnalyzeError, analyze_file
from trendbot.collectors import (
    DEFAULT_GITHUB_QUERIES,
    GitHubCollector,
    HackerNewsCollector,
    ProductHuntCollector,
)
from trendbot.collectors.github import CollectorError as GitHubCollectorError
from trendbot.collectors.hackernews import CollectorError as HackerNewsCollectorError
from trendbot.collectors.producthunt import CollectorError as ProductHuntCollectorError
from trendbot.config import Settings
from trendbot.models import Signal
from trendbot.openai_client import OpenAIClient, OpenAIClientError
from trendbot.reporting import report_from_file
from trendbot.utils import deduplicate_signals, parse_window, write_jsonl

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


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
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Max signals per source"),
    ] = 30,
) -> None:
    """Collect trend signals from GitHub, Hacker News, and optional Product Hunt."""

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
        cards = analyze_file(input_path=in_path, output_path=out, top=top, client=client)
    except (AnalyzeError, OpenAIClientError, ValueError) as exc:
        raise typer.Exit(code=_exit_with_error(str(exc))) from exc

    console.print(f"[bold]Saved {len(cards)} opportunity cards to {out}[/bold]")


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
