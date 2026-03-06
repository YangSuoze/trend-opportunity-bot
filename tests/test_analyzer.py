from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from trendbot.analyzer import analyze_file, analyze_signals
from trendbot.models import Signal
from trendbot.openai_client import OpenAIClient
from trendbot.utils import read_jsonl, write_jsonl


def test_analyze_signals_parses_json_response() -> None:
    response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "target_user": "Indie hackers",
                            "trigger": "Need to validate RAG demand",
                            "pain": "Hard to pick tractable idea",
                            "existing_alternatives": "Manual trend scanning",
                            "solution": "RAG trend-to-opportunity CLI",
                            "pricing_reason": "Saves days of research",
                            "validation_7d": "Interview 10 users and ship landing page",
                            "success_signal": "3 paid pilots",
                            "zh_summary": "面向独立开发者的趋势机会分析工具。",
                            "zh_analysis": (
                                "现在需求增长，风险在于同质化，差异化在于自动化验证流程。"
                            ),
                            "scoring": {
                                "demand": 4,
                                "urgency": 4,
                                "distribution": 3,
                                "feasibility": 5,
                                "monetization": 4,
                                "defensibility": 3,
                                "total": 23,
                            },
                        }
                    )
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        system_prompt = body["messages"][0]["content"]
        user_prompt = body["messages"][1]["content"]
        assert "zh_summary" in system_prompt
        assert "zh_analysis" in system_prompt
        assert "zh_summary" in user_prompt
        assert "zh_analysis" in user_prompt
        return httpx.Response(200, json=response_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = OpenAIClient(
        base_url="https://example.com/v1",
        api_key="k",
        model="qwen3-max",
        client=client,
    )

    signal = Signal(
        source="github",
        title="acme/rag-tool",
        url="https://github.com/acme/rag-tool",
        description="RAG toolkit",
        tags=["github", "python"],
        metrics={"stargazer_count": 123},
        captured_at=datetime.now(UTC),
        fingerprint="fp-1",
    )

    cards = analyze_signals([signal], top=1, client=llm)

    assert len(cards) == 1
    assert cards[0].solution == "RAG trend-to-opportunity CLI"
    assert cards[0].zh_summary == "面向独立开发者的趋势机会分析工具。"
    assert cards[0].zh_analysis == "现在需求增长，风险在于同质化，差异化在于自动化验证流程。"
    assert cards[0].scoring.total == 23


def test_analyze_file_resumes_and_deduplicates_existing_output(tmp_path: Path) -> None:
    request_titles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        user_prompt = body["messages"][1]["content"]
        title = _extract_title(user_prompt)
        request_titles.append(title)
        return httpx.Response(200, json=_completion_payload(solution=f"solution:{title}"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = OpenAIClient(
        base_url="https://example.com/v1",
        api_key="k",
        model="qwen3-max",
        client=client,
    )

    input_path = tmp_path / "signals.jsonl"
    output_path = tmp_path / "opportunities.jsonl"

    write_jsonl(
        input_path,
        [
            _signal(title="alpha", fingerprint="fp-alpha"),
            _signal(title="beta", fingerprint="fp-beta"),
        ],
    )
    first_cards = analyze_file(input_path=input_path, output_path=output_path, top=10, client=llm)
    assert len(first_cards) == 2
    assert [row["source_fingerprint"] for row in read_jsonl(output_path)] == ["fp-alpha", "fp-beta"]

    write_jsonl(
        input_path,
        [
            _signal(title="alpha", fingerprint="fp-alpha"),
            _signal(title="beta", fingerprint="fp-beta"),
            _signal(title="gamma", fingerprint="fp-gamma"),
        ],
    )
    second_cards = analyze_file(input_path=input_path, output_path=output_path, top=10, client=llm)

    rows = read_jsonl(output_path)
    assert len(second_cards) == 1
    assert [row["source_fingerprint"] for row in rows] == ["fp-alpha", "fp-beta", "fp-gamma"]
    assert request_titles == ["alpha", "beta", "gamma"]


def test_analyze_file_continues_after_model_error_and_appends_successes(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        title = _extract_title(body["messages"][1]["content"])
        if title == "beta":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})
        return httpx.Response(200, json=_completion_payload(solution=f"solution:{title}"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = OpenAIClient(
        base_url="https://example.com/v1",
        api_key="k",
        model="qwen3-max",
        client=client,
    )

    input_path = tmp_path / "signals.jsonl"
    output_path = tmp_path / "opportunities.jsonl"
    errors: list[str] = []

    write_jsonl(
        input_path,
        [
            _signal(title="alpha", fingerprint="fp-alpha"),
            _signal(title="beta", fingerprint="fp-beta"),
            _signal(title="gamma", fingerprint="fp-gamma"),
        ],
    )

    cards = analyze_file(
        input_path=input_path,
        output_path=output_path,
        top=10,
        client=llm,
        resume=False,
        on_error=lambda signal, exc: errors.append(f"{signal.title}:{exc}"),
    )

    rows = read_jsonl(output_path)
    assert len(cards) == 2
    assert [row["source_fingerprint"] for row in rows] == ["fp-alpha", "fp-gamma"]
    assert len(errors) == 1
    assert errors[0].startswith("beta:")


def _signal(*, title: str, fingerprint: str) -> Signal:
    return Signal(
        source="github",
        title=title,
        url=f"https://example.com/{title}",
        description=f"description:{title}",
        tags=["github"],
        metrics={"stargazer_count": 100},
        captured_at=datetime.now(UTC),
        fingerprint=fingerprint,
    )


def _extract_title(user_prompt: str) -> str:
    for line in user_prompt.splitlines():
        if line.startswith("title: "):
            return line.replace("title: ", "", 1).strip()
    raise AssertionError("missing title in user prompt")


def _completion_payload(*, solution: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "target_user": "Indie hackers",
                            "trigger": "Need to validate demand",
                            "pain": "Hard to pick tractable idea",
                            "existing_alternatives": "Manual trend scanning",
                            "solution": solution,
                            "pricing_reason": "Saves days of research",
                            "validation_7d": "Interview 10 users and ship landing page",
                            "success_signal": "3 paid pilots",
                            "zh_summary": "摘要",
                            "zh_analysis": "分析",
                            "scoring": {
                                "demand": 4,
                                "urgency": 4,
                                "distribution": 3,
                                "feasibility": 5,
                                "monetization": 4,
                                "defensibility": 3,
                                "total": 23,
                            },
                        }
                    )
                }
            }
        ]
    }
