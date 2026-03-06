from __future__ import annotations

import time
from typing import Any

import httpx


class RequestError(RuntimeError):
    pass


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> httpx.Response:
    if json_body is not None and form_body is not None:
        raise ValueError("json_body and form_body are mutually exclusive")

    attempt = 0

    while True:
        attempt += 1
        try:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                data=form_body,
            )
        except httpx.RequestError as exc:
            if attempt > retries:
                raise RequestError(f"request failed after {attempt - 1} retries: {exc}") from exc
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
            continue

        if response.status_code in {429, 500, 502, 503, 504} and attempt <= retries:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                delay = backoff_seconds * (2 ** (attempt - 1))
            time.sleep(min(delay, 30.0))
            continue

        if response.status_code >= 400:
            snippet = response.text[:400].replace("\n", " ")
            raise RequestError(f"HTTP {response.status_code} from {url}: {snippet}")

        return response


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> Any:
    response = request_with_retries(
        client,
        method,
        url,
        headers=headers,
        params=params,
        json_body=json_body,
        form_body=form_body,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )

    try:
        return response.json()
    except ValueError as exc:
        snippet = response.text[:200].replace("\n", " ")
        raise RequestError(f"invalid JSON response from {url}: {snippet}") from exc
