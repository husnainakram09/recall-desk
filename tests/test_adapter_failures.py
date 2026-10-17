"""Token Factory adapter under failure: status codes, retry, timeout, bad bodies."""

import pytest
import requests

from config import AMDSettings
from extraction import token_factory
from extraction.token_factory import ExtractionError, TokenFactoryAdapter
from tests.test_provenance import FakeResponse

SETTINGS = AMDSettings("https://amd.example.test/v1", "key", "model")
GOOD = {"choices": [{"message": {"content": '{"items": []}'}}]}


def _adapter(monkeypatch, *responses):
    queue = list(responses)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(token_factory.requests, "post", fake_post)
    return TokenFactoryAdapter(SETTINGS), calls


def test_rate_limit_is_reported_without_retry(monkeypatch):
    adapter, calls = _adapter(monkeypatch, FakeResponse(429, {"error": "slow down"}))

    with pytest.raises(ExtractionError, match="HTTP 429 after 1 attempt"):
        adapter.extract("text")
    assert len(calls) == 1
    assert adapter.last_call_meta.status_code == 429


def test_server_error_is_retried_once_then_succeeds(monkeypatch):
    adapter, calls = _adapter(
        monkeypatch, FakeResponse(500, {"error": "x"}), FakeResponse(200, GOOD)
    )

    assert adapter.extract("text") == {"items": []}
    assert len(calls) == 2
    assert adapter.last_call_meta.attempts == 2


def test_repeated_server_error_fails_after_one_retry(monkeypatch):
    adapter, calls = _adapter(
        monkeypatch, FakeResponse(503, None), FakeResponse(500, None)
    )

    with pytest.raises(ExtractionError, match="HTTP 500 after 2 attempt"):
        adapter.extract("text")
    assert len(calls) == 2


def test_timeout_propagates_for_the_ui_to_report(monkeypatch):
    adapter, _ = _adapter(monkeypatch, requests.Timeout("read timed out"))

    with pytest.raises(requests.Timeout):
        adapter.extract("text")


@pytest.mark.parametrize(
    "body",
    [None, {}, {"choices": []}, {"choices": [{"message": {}}]}],
    ids=["non-json", "empty", "no-choices", "no-content"],
)
def test_response_without_a_model_message_is_an_extraction_error(monkeypatch, body):
    adapter, _ = _adapter(monkeypatch, FakeResponse(200, body))

    with pytest.raises(ExtractionError):
        adapter.extract("text")


def test_non_json_model_output_is_an_extraction_error(monkeypatch):
    body = {"choices": [{"message": {"content": "Sure! Here are the items."}}]}
    adapter, _ = _adapter(monkeypatch, FakeResponse(200, body))

    with pytest.raises(ExtractionError, match="not valid JSON"):
        adapter.extract("text")
