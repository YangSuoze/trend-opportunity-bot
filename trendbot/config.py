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

    @classmethod
    def load(cls) -> Settings:
        load_dotenv()
        return cls(
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "qwen3-max"),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            producthunt_token=os.getenv("PRODUCTHUNT_TOKEN", ""),
        )
