from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="qwen3-max")
    github_token: str = Field(default="")
    producthunt_token: str = Field(default="")
    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(
        default="python:trend-opportunity-bot:v0.1.0 (by /u/unknown)"
    )
    reddit_subreddits: list[str] = Field(default_factory=list)
    devto_tags: list[str] = Field(default_factory=list)
    substack_feeds: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls) -> Settings:
        load_dotenv()
        return cls(
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "qwen3-max"),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            producthunt_token=os.getenv("PRODUCTHUNT_TOKEN", ""),
            reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            reddit_user_agent=os.getenv(
                "REDDIT_USER_AGENT",
                "python:trend-opportunity-bot:v0.1.0 (by /u/unknown)",
            ),
            reddit_subreddits=_csv_env("REDDIT_SUBREDDITS"),
            devto_tags=_csv_env("DEVTO_TAGS"),
            substack_feeds=_csv_env("SUBSTACK_FEEDS"),
        )


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    values: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        values.append(cleaned)
    return values
