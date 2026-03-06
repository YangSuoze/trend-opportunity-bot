from __future__ import annotations

from pathlib import Path

ARTIFACTS_DIR = Path("artifacts")
SIGNALS_PATH = ARTIFACTS_DIR / "signals.jsonl"
OPPORTUNITIES_PATH = ARTIFACTS_DIR / "opportunities.jsonl"
REPORT_PATH = ARTIFACTS_DIR / "report.md"


def artifact_paths() -> dict[str, str]:
    return {
        "signals": str(SIGNALS_PATH),
        "opportunities": str(OPPORTUNITIES_PATH),
        "report": str(REPORT_PATH),
    }
