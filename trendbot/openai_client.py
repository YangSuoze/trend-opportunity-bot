from __future__ import annotations

from typing import Any

import httpx

from trendbot.http import RequestError, request_json


class OpenAIClientError(RuntimeError):
    pass


class OpenAIClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model = model
        self.client = client or httpx.Client(timeout=45.0)

    def chat_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        if not self.api_key:
            raise OpenAIClientError("OPENAI_API_KEY is required for analyze command")

        endpoint = self._chat_endpoint()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            result = request_json(
                self.client,
                "POST",
                endpoint,
                headers=headers,
                json_body=payload,
                retries=4,
                backoff_seconds=1.0,
            )
        except RequestError as exc:
            raise OpenAIClientError(f"chat completion failed: {exc}") from exc

        try:
            message = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIClientError("unexpected completion payload shape") from exc

        if isinstance(message, str):
            return message

        # Some OpenAI-compatible providers return segmented content blocks.
        if isinstance(message, list):
            chunks = []
            for part in message:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
            if chunks:
                return "".join(chunks)

        raise OpenAIClientError("no text content returned by model")

    def _chat_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"
