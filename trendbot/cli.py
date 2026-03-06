from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from trendbot.analyzer import AnalyzeError, analyze_file
from trendbot.config import Settings
from trendbot.openai_client import OpenAIClient, OpenAIClientError
from trendbot.pipeline import collect_signals
from trendbot.reporting import report_from_file
from trendbot.utils import write_jsonl

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
    source_labels = {
        "github": "GitHub",
        "hackernews": "Hacker News",
        "producthunt": "Product Hunt",
        "reddit": "Reddit",
        "devto": "DEV.to",
        "substack": "Substack",
    }

    def on_source_result(source: str, count: int, error: str | None) -> None:
        label = source_labels.get(source, source)
        if error:
            if "skipping" in error.lower() or "disabled" in error.lower():
                console.print(f"[yellow]{error}[/yellow]")
                return
            console.print(f"[yellow]{label} collector failed:[/yellow] {error}")
            return
        console.print(f"[green]{label}:[/green] collected {count} signals")

    try:
        unique_signals = collect_signals(
            settings=settings,
            window=window,
            limit=limit,
            github_query=github_query,
            github_language=github_language,
            hn_mode=hn_mode,
            reddit_subreddit=reddit_subreddit,
            devto_tag=devto_tag,
            substack_feed=substack_feed,
            on_source_result=on_source_result,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--window") from exc

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


@app.command()
def serve(
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="Local bind port"),
    ] = 8000,
    reload: Annotated[
        bool,
        typer.Option(
            "--reload/--no-reload",
            help="Enable auto-reload (development only)",
        ),
    ] = False,
) -> None:
    """Run the local API server bound to 127.0.0.1."""

    try:
        import uvicorn
    except ImportError as exc:
        raise typer.Exit(
            code=_exit_with_error(
                "uvicorn is not installed. Install dependencies with `pip install -e .`."
            )
        ) from exc

    from trendbot.server import create_app

    console.print(f"[bold]Serving API at http://127.0.0.1:{port}[/bold]")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, reload=reload)


def _exit_with_error(message: str) -> int:
    console.print(f"[red]{message}[/red]")
    return 1


if __name__ == "__main__":
    app()
