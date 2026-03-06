from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from trendbot.analyzer import analyze_signals
from trendbot.models import Signal
from trendbot.openai_client import OpenAIClient


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
