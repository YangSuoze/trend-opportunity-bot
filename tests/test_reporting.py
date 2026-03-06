from __future__ import annotations

import json

from trendbot.models import OpportunityCard, OpportunityScoring
from trendbot.reporting import render_report, report_from_file


def test_render_report_sorts_by_total_score() -> None:
    low = OpportunityCard(
        source="github",
        source_title="repo-low",
        source_url="https://github.com/acme/low",
        source_fingerprint="low",
        target_user="A",
        trigger="A",
        pain="A",
        existing_alternatives="A",
        solution="Low",
        pricing_reason="A",
        validation_7d="A",
        success_signal="A",
        zh_summary="低分机会摘要",
        zh_analysis="低分机会分析",
        scoring=OpportunityScoring(
            demand=1,
            urgency=1,
            distribution=1,
            feasibility=1,
            monetization=1,
            defensibility=1,
        ),
    )
    high = OpportunityCard(
        source="github",
        source_title="repo-high",
        source_url="https://github.com/acme/high",
        source_fingerprint="high",
        target_user="B",
        trigger="B",
        pain="B",
        existing_alternatives="B",
        solution="High",
        pricing_reason="B",
        validation_7d="B",
        success_signal="B",
        zh_summary="高分机会摘要",
        zh_analysis="高分机会分析",
        scoring=OpportunityScoring(
            demand=5,
            urgency=5,
            distribution=5,
            feasibility=5,
            monetization=4,
            defensibility=4,
        ),
    )

    output = render_report([low, high])

    first_high_index = output.find("repo-high")
    first_low_index = output.find("repo-low")
    assert first_high_index != -1
    assert first_low_index != -1
    assert first_high_index < first_low_index
    assert "#### zh_summary" in output
    assert "高分机会摘要" in output
    assert "#### zh_analysis" in output
    assert "高分机会分析" in output


def test_report_from_file_accepts_legacy_cards_without_zh_fields(tmp_path) -> None:
    input_path = tmp_path / "opportunities.jsonl"
    output_path = tmp_path / "report.md"
    legacy_card = {
        "source": "github",
        "source_title": "legacy-repo",
        "source_url": "https://github.com/acme/legacy",
        "source_fingerprint": "legacy",
        "target_user": "Legacy users",
        "trigger": "Legacy trigger",
        "pain": "Legacy pain",
        "existing_alternatives": "Legacy alternatives",
        "solution": "Legacy opportunity",
        "pricing_reason": "Legacy pricing",
        "validation_7d": "Legacy validation",
        "success_signal": "Legacy success",
        "scoring": {
            "demand": 3,
            "urgency": 3,
            "distribution": 3,
            "feasibility": 3,
            "monetization": 3,
            "defensibility": 3,
        },
    }
    input_path.write_text(json.dumps(legacy_card) + "\n", encoding="utf-8")

    markdown = report_from_file(input_path, output_path)

    assert "Legacy opportunity" in markdown
    assert "#### zh_summary" in markdown
    assert "#### zh_analysis" in markdown
    assert output_path.exists()
