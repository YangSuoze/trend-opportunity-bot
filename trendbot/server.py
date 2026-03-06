from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from trendbot import __version__
from trendbot.analyzer import analyze_file
from trendbot.artifacts import OPPORTUNITIES_PATH, REPORT_PATH, SIGNALS_PATH, artifact_paths
from trendbot.config import Settings
from trendbot.models import Signal
from trendbot.openai_client import OpenAIClient
from trendbot.pipeline import collect_signals
from trendbot.reporting import report_from_file
from trendbot.utils import read_jsonl, write_jsonl

TERMINAL_JOB_STATUSES = {"done", "error"}


class CollectRequest(BaseModel):
    window: str = Field(..., description="Collection window, e.g. 24h or 7d")
    limit: int = Field(default=30, ge=1, le=500)


class AnalyzeRequest(BaseModel):
    top: int = Field(..., ge=1, le=500)
    resume: bool = Field(default=True)


class ReportRequest(BaseModel):
    pass


@dataclass(slots=True)
class JobEvent:
    id: int
    type: str
    data: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class JobRecord:
    id: str
    kind: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: _utc_now_iso())
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)
    next_event_id: int = 1


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self, *, kind: str) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = JobRecord(id=job_id, kind=kind)
        return job_id

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = "running"
            job.started_at = _utc_now_iso()

    def mark_done(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = "done"
            job.finished_at = _utc_now_iso()

    def mark_error(self, job_id: str, *, message: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = "error"
            job.error = message
            job.finished_at = _utc_now_iso()

    def append_event(self, job_id: str, *, event_type: str, data: dict[str, Any]) -> JobEvent:
        with self._lock:
            job = self._require(job_id)
            event = JobEvent(
                id=job.next_event_id,
                type=event_type,
                data=data,
                created_at=_utc_now_iso(),
            )
            job.events.append(event)
            job.next_event_id += 1
        return event

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return _job_snapshot(job)

    def events_since(self, job_id: str, *, last_seen: int) -> list[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return []
            return [_event_snapshot(event) for event in job.events if event.id > last_seen]

    def _require(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return job


def format_sse_event(event_type: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event_type}\ndata: {serialized}\n\n"


def create_app(*, job_registry: JobRegistry | None = None) -> FastAPI:
    app = FastAPI(title="trendbot-local-api", version=__version__)
    registry = job_registry or JobRegistry()
    app.state.job_registry = registry
    app.state.background_tasks = set()

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        return {"version": __version__, "artifacts": artifact_paths()}

    @app.get("/api/artifacts/signals")
    async def api_signals_artifact() -> list[dict[str, Any]]:
        return _read_jsonl_or_empty(SIGNALS_PATH)

    @app.get("/api/artifacts/opportunities")
    async def api_opportunities_artifact() -> list[dict[str, Any]]:
        return _read_jsonl_or_empty(OPPORTUNITIES_PATH)

    @app.get("/api/artifacts/report")
    async def api_report_artifact() -> PlainTextResponse:
        text = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""
        return PlainTextResponse(text, media_type="text/markdown")

    @app.post("/api/collect")
    async def api_collect(payload: CollectRequest) -> dict[str, str]:
        job_id = registry.create(kind="collect")
        _schedule_background_job(
            app,
            _run_job(
                registry=registry,
                job_id=job_id,
                worker=lambda: _collect_worker(
                    payload=payload,
                    registry=registry,
                    job_id=job_id,
                ),
            ),
        )
        return {"jobId": job_id}

    @app.post("/api/analyze")
    async def api_analyze(payload: AnalyzeRequest) -> dict[str, str]:
        job_id = registry.create(kind="analyze")
        _schedule_background_job(
            app,
            _run_job(
                registry=registry,
                job_id=job_id,
                worker=lambda: _analyze_worker(
                    payload=payload,
                    registry=registry,
                    job_id=job_id,
                ),
            ),
        )
        return {"jobId": job_id}

    @app.post("/api/report")
    async def api_report(_payload: ReportRequest) -> dict[str, str]:
        job_id = registry.create(kind="report")
        _schedule_background_job(
            app,
            _run_job(
                registry=registry,
                job_id=job_id,
                worker=lambda: _report_worker(registry=registry, job_id=job_id),
            ),
        )
        return {"jobId": job_id}

    @app.get("/api/jobs/{job_id}")
    async def api_job_status(job_id: str) -> dict[str, Any]:
        snapshot = registry.snapshot(job_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="job not found")
        return snapshot

    @app.get("/api/jobs/{job_id}/events")
    async def api_job_events(job_id: str) -> StreamingResponse:
        if not registry.snapshot(job_id):
            raise HTTPException(status_code=404, detail="job not found")

        async def stream() -> Any:
            last_seen = 0
            while True:
                events = registry.events_since(job_id, last_seen=last_seen)
                for event in events:
                    last_seen = event["id"]
                    yield format_sse_event(event["type"], event["data"])

                snapshot = registry.snapshot(job_id)
                if not snapshot:
                    break
                if snapshot["status"] in TERMINAL_JOB_STATUSES and not events:
                    break

                await anyio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return app


async def _run_job(
    *,
    registry: JobRegistry,
    job_id: str,
    worker: Callable[[], dict[str, int]],
) -> None:
    registry.mark_running(job_id)
    try:
        counts = await anyio.to_thread.run_sync(worker)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        registry.append_event(job_id, event_type="error", data={"message": message})
        registry.mark_error(job_id, message=message)
        return

    registry.append_event(job_id, event_type="done", data={"counts": counts})
    registry.mark_done(job_id)


def _schedule_background_job(app: FastAPI, coroutine: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coroutine)
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)


def _collect_worker(
    *,
    payload: CollectRequest,
    registry: JobRegistry,
    job_id: str,
) -> dict[str, int]:
    settings = Settings.load()
    signals = collect_signals(
        settings=settings,
        window=payload.window,
        limit=payload.limit,
        on_source_result=lambda source, count, error: _emit_source_status(
            registry=registry,
            job_id=job_id,
            source=source,
            count=count,
            error=error,
        ),
    )
    write_jsonl(SIGNALS_PATH, signals)
    _emit_signal_progress(registry=registry, job_id=job_id, signals=signals)
    return {"signals": len(signals)}


def _analyze_worker(
    *,
    payload: AnalyzeRequest,
    registry: JobRegistry,
    job_id: str,
) -> dict[str, int]:
    settings = Settings.load()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for analyze command")

    client = OpenAIClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    cards = analyze_file(
        input_path=SIGNALS_PATH,
        output_path=OPPORTUNITIES_PATH,
        top=payload.top,
        client=client,
        resume=payload.resume,
        on_progress=lambda index, total, signal: _emit_progress_event(
            registry=registry,
            job_id=job_id,
            index=index,
            total=total,
            title=signal.title,
            source=signal.source,
        ),
        on_error=lambda signal, exc: registry.append_event(
            job_id,
            event_type="error",
            data={"message": f"{signal.title} (source={signal.source}) -> {exc}"},
        ),
        on_card=lambda card: registry.append_event(
            job_id,
            event_type="card",
            data={"card": card.model_dump(mode="json")},
        ),
    )

    all_rows = _read_jsonl_or_empty(OPPORTUNITIES_PATH)
    return {"new_cards": len(cards), "total_cards": len(all_rows)}


def _report_worker(*, registry: JobRegistry, job_id: str) -> dict[str, int]:
    _emit_progress_event(
        registry=registry,
        job_id=job_id,
        index=1,
        total=1,
        title="Generate report",
        source="report",
    )
    markdown = report_from_file(OPPORTUNITIES_PATH, REPORT_PATH)
    rows = _read_jsonl_or_empty(OPPORTUNITIES_PATH)
    return {"cards": len(rows), "bytes": len(markdown)}


def _emit_source_status(
    *,
    registry: JobRegistry,
    job_id: str,
    source: str,
    count: int,
    error: str | None,
) -> None:
    if error:
        registry.append_event(
            job_id,
            event_type="error",
            data={"message": f"{source}: {error}"},
        )
        return

    registry.append_event(
        job_id,
        event_type="progress",
        data={
            "i": count,
            "total": count,
            "title": f"Collected {count} signals",
            "source": source,
        },
    )


def _emit_signal_progress(
    *,
    registry: JobRegistry,
    job_id: str,
    signals: list[Signal],
) -> None:
    total = len(signals)
    for index, signal in enumerate(signals, start=1):
        _emit_progress_event(
            registry=registry,
            job_id=job_id,
            index=index,
            total=total,
            title=signal.title,
            source=signal.source,
        )


def _emit_progress_event(
    *,
    registry: JobRegistry,
    job_id: str,
    index: int,
    total: int,
    title: str,
    source: str,
) -> None:
    registry.append_event(
        job_id,
        event_type="progress",
        data={
            "i": index,
            "total": total,
            "title": title,
            "source": source,
        },
    )


def _read_jsonl_or_empty(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _job_snapshot(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "event_count": len(job.events),
    }


def _event_snapshot(event: JobEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type,
        "data": event.data,
        "created_at": event.created_at,
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


app = create_app()
