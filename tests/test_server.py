from __future__ import annotations

from fastapi.testclient import TestClient

from trendbot.server import JobRegistry, create_app, format_sse_event


def test_job_registry_tracks_lifecycle_and_events() -> None:
    registry = JobRegistry()
    job_id = registry.create(kind="analyze")

    initial = registry.snapshot(job_id)
    assert initial is not None
    assert initial["status"] == "queued"

    registry.mark_running(job_id)
    registry.append_event(
        job_id,
        event_type="progress",
        data={"i": 1, "total": 2, "title": "alpha", "source": "github"},
    )
    registry.mark_done(job_id)

    snapshot = registry.snapshot(job_id)
    assert snapshot is not None
    assert snapshot["status"] == "done"
    assert snapshot["event_count"] == 1

    events = registry.events_since(job_id, last_seen=0)
    assert len(events) == 1
    assert events[0]["type"] == "progress"
    assert events[0]["data"]["title"] == "alpha"


def test_format_sse_event_shape() -> None:
    payload = {"i": 1, "total": 2, "title": "alpha", "source": "github"}
    event = format_sse_event("progress", payload)
    assert event == (
        'event: progress\n'
        'data: {"i":1,"total":2,"title":"alpha","source":"github"}\n\n'
    )


def test_job_events_endpoint_streams_sse_records() -> None:
    registry = JobRegistry()
    job_id = registry.create(kind="collect")
    registry.mark_running(job_id)
    registry.append_event(
        job_id,
        event_type="progress",
        data={"i": 1, "total": 1, "title": "collect", "source": "github"},
    )
    registry.append_event(
        job_id,
        event_type="done",
        data={"counts": {"signals": 1}},
    )
    registry.mark_done(job_id)

    app = create_app(job_registry=registry)
    with TestClient(app) as client:
        with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: progress" in body
    assert "event: done" in body
    assert '"signals":1' in body
