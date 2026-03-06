from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from trendbot.models import OpportunityCard, Signal
from trendbot.openai_client import OpenAIClient, OpenAIClientError
from trendbot.utils import append_jsonl, deduplicate_signals, read_jsonl, write_jsonl

_SYSTEM_PROMPT = """
You are a product strategist. Return ONLY valid JSON.
Given one trend signal, produce one concise opportunity card.
Use Chinese (zh-CN) for zh_summary and zh_analysis.
Scoring dimensions must be integers 0..5 for:
- demand
- urgency
- distribution
- feasibility
- monetization
- defensibility
And include total as the sum.
Required JSON keys:
- target_user
- trigger
- pain
- existing_alternatives
- solution
- pricing_reason
- validation_7d
- success_signal
- zh_summary
- zh_analysis
- scoring
""".strip()


class AnalyzeError(RuntimeError):
    pass


ProgressCallback = Callable[[int, int, Signal], None]
ErrorCallback = Callable[[Signal, Exception], None]
CardCallback = Callable[[OpportunityCard], None]


def analyze_signals(
    signals: list[Signal],
    *,
    top: int,
    client: OpenAIClient,
    seen_fingerprints: set[str] | None = None,
    on_progress: ProgressCallback | None = None,
    on_error: ErrorCallback | None = None,
    on_card: CardCallback | None = None,
) -> list[OpportunityCard]:
    unique_signals = deduplicate_signals(signals)
    ranked = rank_signals(unique_signals)
    selected = ranked[:top]
    seen = seen_fingerprints if seen_fingerprints is not None else set()
    to_analyze = [signal for signal in selected if signal.fingerprint not in seen]
    total = len(to_analyze)

    cards: list[OpportunityCard] = []

    for index, signal in enumerate(to_analyze, start=1):
        if on_progress:
            on_progress(index, total, signal)

        user_prompt = _build_user_prompt(signal)

        try:
            raw = client.chat_completion(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
            )
            payload = _parse_json_object(raw)
            card = OpportunityCard(
                source=signal.source,
                source_title=signal.title,
                source_url=signal.url,
                source_fingerprint=signal.fingerprint,
                target_user=str(payload.get("target_user", "")).strip(),
                trigger=str(payload.get("trigger", "")).strip(),
                pain=str(payload.get("pain", "")).strip(),
                existing_alternatives=str(payload.get("existing_alternatives", "")).strip(),
                solution=str(payload.get("solution", "")).strip(),
                pricing_reason=str(payload.get("pricing_reason", "")).strip(),
                validation_7d=str(payload.get("validation_7d", "")).strip(),
                success_signal=str(payload.get("success_signal", "")).strip(),
                zh_summary=str(payload.get("zh_summary", "")).strip(),
                zh_analysis=str(payload.get("zh_analysis", "")).strip(),
                scoring=payload.get("scoring", {}),
            )
            cards.append(card)
            seen.add(signal.fingerprint)
            if on_card:
                on_card(card)
        except (OpenAIClientError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if on_error:
                on_error(signal, exc)
            continue

        # Small pause to be friendly to hosted model rate limits.
        if index < total:
            time.sleep(0.2)

    return cards


def analyze_file(
    *,
    input_path: Path,
    output_path: Path,
    top: int,
    client: OpenAIClient,
    resume: bool = True,
    on_progress: ProgressCallback | None = None,
    on_error: ErrorCallback | None = None,
) -> list[OpportunityCard]:
    rows = read_jsonl(input_path)
    signals = [Signal.model_validate(row) for row in rows]
    seen_fingerprints: set[str] = set()

    if resume and output_path.exists():
        seen_fingerprints = _load_source_fingerprints(output_path)
    else:
        write_jsonl(output_path, [])

    cards = analyze_signals(
        signals,
        top=top,
        client=client,
        seen_fingerprints=seen_fingerprints,
        on_progress=on_progress,
        on_error=on_error,
        on_card=lambda card: append_jsonl(output_path, [card]),
    )
    return cards


def _load_source_fingerprints(path: Path) -> set[str]:
    rows = read_jsonl(path)
    fingerprints: set[str] = set()
    for row in rows:
        value = row.get("source_fingerprint")
        if isinstance(value, str) and value:
            fingerprints.add(value)
    return fingerprints


def rank_signals(signals: list[Signal]) -> list[Signal]:
    def score(signal: Signal) -> float:
        metrics = signal.metrics

        stars = _as_float(metrics.get("stargazer_count"))
        forks = _as_float(metrics.get("fork_count"))
        hn_score = _as_float(metrics.get("score"))
        votes = _as_float(metrics.get("votes_count"))
        comments = _as_float(metrics.get("comments"))

        return stars + (forks * 0.6) + hn_score + votes + (comments * 0.3)

    return sorted(signals, key=score, reverse=True)


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _build_user_prompt(signal: Signal) -> str:
    return (
        "Create one opportunity card from this signal.\n"
        "Keep each field concrete and concise.\n"
        "Return zh_summary and zh_analysis in Chinese (zh-CN).\n"
        "Return JSON with keys: target_user, trigger, pain, existing_alternatives, "
        "solution, pricing_reason, validation_7d, success_signal, zh_summary, "
        "zh_analysis, scoring.\n"
        "Signal:\n"
        f"source: {signal.source}\n"
        f"title: {signal.title}\n"
        f"url: {signal.url}\n"
        f"description: {signal.description}\n"
        f"tags: {', '.join(signal.tags)}\n"
        f"metrics: {json.dumps(signal.metrics, ensure_ascii=True)}\n"
    )


def _parse_json_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()

    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(raw[start : end + 1])

    raise json.JSONDecodeError("no JSON object found", raw, 0)
