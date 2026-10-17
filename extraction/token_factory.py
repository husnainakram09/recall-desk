"""AMD Token Factory adapter: OpenAI-compatible chat completions, JSON output."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

from config import AMDSettings, load_amd_settings
from extraction.prompts import SYSTEM_PROMPT

TIMEOUT_S = 120  # shared endpoint: reasoning models measured at ~60 s
MAX_ATTEMPTS = 2  # one retry, on 5xx only


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CallMeta:
    endpoint: str  # the URL called, from AMD_API_BASE; never includes the key
    called_at_utc: str  # start of the final attempt, ISO 8601 with Z
    request_id: str | None
    latency_ms: float  # wall time of the final attempt
    status_code: int
    attempts: int
    model: str | None  # as reported by the endpoint, else AMD_MODEL
    usage: dict | None


class TokenFactoryAdapter:
    def __init__(
        self,
        settings: AMDSettings | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self.settings = settings or load_amd_settings()
        self.system_prompt = system_prompt
        self.last_call_meta: CallMeta | None = None
        self.last_raw_response: dict | None = None

    def extract(self, text: str) -> dict:
        url = self.settings.api_base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

        for attempt in range(1, MAX_ATTEMPTS + 1):
            called_at = datetime.now(UTC).isoformat(timespec="seconds")
            started = time.perf_counter()
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
            latency_ms = (time.perf_counter() - started) * 1000
            if resp.status_code < 500 or attempt == MAX_ATTEMPTS:
                break

        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        self.last_raw_response = body or None
        # Recorded for failed calls too, so the request id is never lost.
        self.last_call_meta = CallMeta(
            endpoint=url,
            called_at_utc=called_at.replace("+00:00", "Z"),
            request_id=resp.headers.get("x-request-id") or body.get("id"),
            latency_ms=latency_ms,
            status_code=resp.status_code,
            attempts=attempt,
            model=body.get("model") or self.settings.model,
            usage=body.get("usage"),
        )

        if not resp.ok:
            raise ExtractionError(
                f"Endpoint returned HTTP {resp.status_code} after {attempt} attempt(s): "
                f"{resp.text[:500]}"
            )

        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(_strip_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Model output is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ExtractionError(
                f"Expected a JSON object, got {type(parsed).__name__}"
            )
        return parsed


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
        content = content.rsplit("```", 1)[0]
    return content
