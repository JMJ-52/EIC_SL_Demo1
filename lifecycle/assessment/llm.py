from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

import certifi

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _urlopen(request: urllib.request.Request, timeout: float):
    """Use certifi's CA bundle on macOS Python installations.

    The system Python on a fresh Mac may not have its CA roots wired into
    ``ssl.create_default_context``; urllib then fails before the OpenAI API
    can even see the request.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=TLS_CONTEXT)
    except TypeError:  # pragma: no cover - compatibility with unusual urllib shims
        return urllib.request.urlopen(request, timeout=timeout)


class LLMError(RuntimeError):
    """Raised when an OpenAI call fails, times out, or returns unusable output."""


def call_openai_json(
    api_key: str,
    model: str,
    instructions: str,
    input_content: str | list[dict[str, Any]],
    schema: dict[str, Any],
    schema_name: str,
) -> dict[str, Any]:
    """POST to the OpenAI Responses API and return the parsed structured-output JSON.

    Matches lifecycle/webapp/ai_analysis.py::_call_openai_structured's calling
    convention (stdlib urllib, Responses API, strict json_schema output) -
    this project deliberately does not depend on the `openai` package.
    """
    payload = {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": input_content,
        "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen(request, timeout=60) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LLMError(f"OpenAI API request failed: {error}") from error

    output_text = "".join(
        item.get("text", "")
        for entry in (body.get("output") or [])
        for item in (entry.get("content") or [])
        if item.get("type") == "output_text"
    )
    if not output_text:
        raise LLMError("OpenAI response is empty")
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as error:
        raise LLMError(f"OpenAI response was not valid JSON: {error}") from error

