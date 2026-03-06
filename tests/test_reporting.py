from __future__ import annotations

from trendbot.models import OpportunityCard, OpportunityScoring
from trendbot.reporting import render_report


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
