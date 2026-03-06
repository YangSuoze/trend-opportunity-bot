from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trendbot.models import OpportunityCard
from trendbot.utils import ensure_parent_dir, read_jsonl


def render_report(cards: list[OpportunityCard]) -> str:
    ranked = sorted(cards, key=lambda item: item.scoring.total or 0, reverse=True)

    lines = [
        "# Trend Opportunity Report",
        "",
        f"Generated at: {datetime.now(UTC).isoformat()}",
        "",
        "## Top Opportunities",
        "",
        "| Rank | Total | Source | Opportunity | Target User | Source Link |",
        "|---|---:|---|---|---|---|",
    ]

    for index, card in enumerate(ranked, start=1):
        lines.append(
            "| "
            f"{index} | {card.scoring.total or 0} | {card.source} | "
            f"{_compact(card.solution)} | {_compact(card.target_user)} | "
            f"[{_compact(card.source_title)}]({card.source_url}) |"
        )

    lines.extend(["", "## Cards", ""])

    for index, card in enumerate(ranked, start=1):
        lines.extend(
            [
                f"### {index}. {_compact(card.solution)}",
                f"- Total Score: {card.scoring.total or 0}/30",
                f"- Source: [{card.source_title}]({card.source_url}) ({card.source})",
                f"- Target User: {card.target_user}",
                f"- Trigger: {card.trigger}",
                f"- Pain: {card.pain}",
                f"- Existing Alternatives: {card.existing_alternatives}",
                f"- Pricing Reason: {card.pricing_reason}",
                f"- Validation (7d): {card.validation_7d}",
                f"- Success Signal: {card.success_signal}",
                (
                    "- Scoring: "
                    f"demand={card.scoring.demand}, "
                    f"urgency={card.scoring.urgency}, "
                    f"distribution={card.scoring.distribution}, "
                    f"feasibility={card.scoring.feasibility}, "
                    f"monetization={card.scoring.monetization}, "
                    f"defensibility={card.scoring.defensibility}"
                ),
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def report_from_file(input_path: Path, output_path: Path) -> str:
    rows = read_jsonl(input_path)
    cards = [OpportunityCard.model_validate(row) for row in rows]
    markdown = render_report(cards)
    ensure_parent_dir(output_path)
    output_path.write_text(markdown, encoding="utf-8")
    return markdown


def _compact(value: str, max_len: int = 72) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3] + "..."
