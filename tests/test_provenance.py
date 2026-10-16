"""Extraction provenance: captured from config, persisted with the case, reported."""

import sqlite3
from io import BytesIO

import pytest
from pypdf import PdfReader

from config import AMDSettings
from export.report import build_case_report
from extraction import token_factory
from extraction.token_factory import ExtractionError, TokenFactoryAdapter
from storage.db import connect, init_db
from storage.repository import (
    ExtractionProvenance,
    correct_stock_lot,
    create_case,
    get_revision,
    store_findings,
)
from tests.test_repository import NOTICE, STOCK

SETTINGS = AMDSettings("https://amd.example.test/v1/", "secret-key", "configured-model")
PROVENANCE = ExtractionProvenance(
    endpoint="https://amd.example.test/v1/chat/completions",
    model="Qwen/Qwen3-8B",
    request_id="req-0042",
    latency_ms=1234.5,
    called_at_utc="2026-10-16T09:30:00Z",
    edited_before_save=False,
)


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


def _adapter(monkeypatch, response):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr(token_factory.requests, "post", fake_post)
    return TokenFactoryAdapter(SETTINGS), calls


def test_call_meta_captures_endpoint_from_config(monkeypatch):
    body = {"id": "body-id", "choices": [{"message": {"content": '{"items": []}'}}]}
    adapter, calls = _adapter(
        monkeypatch, FakeResponse(200, body, {"x-request-id": "req-1"})
    )

    adapter.extract("text")
    meta = adapter.last_call_meta

    assert meta.endpoint == calls[0] == "https://amd.example.test/v1/chat/completions"
    assert "secret-key" not in meta.endpoint
    assert meta.request_id == "req-1"
    assert meta.model == "configured-model"  # endpoint did not report one
    assert meta.called_at_utc.endswith("Z") and "T" in meta.called_at_utc


def test_failed_call_still_records_metadata(monkeypatch):
    adapter, _ = _adapter(
        monkeypatch, FakeResponse(401, None, {"x-request-id": "req-denied"})
    )

    with pytest.raises(ExtractionError, match="HTTP 401"):
        adapter.extract("text")

    assert adapter.last_call_meta.status_code == 401
    assert adapter.last_call_meta.request_id == "req-denied"
    assert adapter.last_call_meta.endpoint.endswith("/chat/completions")


def _case(tmp_path, provenance):
    conn = connect(tmp_path / "case.db")
    init_db(conn)
    create_case(
        conn,
        "CASE-P",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=True,
        scope_reviewed=True,
        extraction_provenance=provenance,
    )
    return conn


def test_provenance_round_trips_and_survives_reopen(tmp_path):
    _case(tmp_path, PROVENANCE).close()

    reopened = connect(tmp_path / "case.db")
    assert get_revision(reopened, "CASE-P").extraction_provenance == PROVENANCE
    reopened.close()


def test_provenance_carries_to_later_revisions(tmp_path):
    conn = _case(tmp_path, PROVENANCE)
    store_findings(conn, "CASE-P")

    correct_stock_lot(
        conn, "CASE-P", expected_revision=1, row_id=STOCK.row_id, lot_raw="NEW1"
    )

    latest = get_revision(conn, "CASE-P")
    assert latest.revision == 2
    assert latest.extraction_provenance == PROVENANCE


def test_manual_draft_has_no_provenance(tmp_path):
    conn = _case(tmp_path, None)

    assert get_revision(conn, "CASE-P").extraction_provenance is None


def test_provenance_cannot_be_rewritten(tmp_path):
    conn = _case(tmp_path, PROVENANCE)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"), conn:
        conn.execute("UPDATE cases SET extraction_provenance_json = NULL")


def test_database_created_before_provenance_is_upgraded(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        INSERT INTO cases VALUES ('OLD-1', 'https://example.org', '2026-10-14T00:00:00Z');
        """
    )
    old.close()

    conn = connect(path)
    init_db(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(cases)")}
    assert "extraction_provenance_json" in columns
    old_row = conn.execute(
        "SELECT extraction_provenance_json FROM cases WHERE case_id = 'OLD-1'"
    ).fetchone()
    assert old_row[0] is None


def _pdf_text(conn):
    pdf = build_case_report(conn, "CASE-P")
    return " ".join(
        " ".join(page.extract_text().split()) for page in PdfReader(BytesIO(pdf)).pages
    )


def test_report_prints_extraction_provenance(tmp_path):
    conn = _case(tmp_path, PROVENANCE)
    store_findings(conn, "CASE-P")

    text = _pdf_text(conn)

    assert "Extraction provenance" in text
    assert "Endpoint: https://amd.example.test/v1/chat/completions" in text
    assert "Model: Qwen/Qwen3-8B" in text
    assert "Request ID: req-0042" in text
    assert "Latency: 1,234 ms" in text or "Latency: 1,235 ms" in text
    assert "Called at (UTC): 2026-10-16T09:30:00Z" in text
    assert "Draft edited by reviewer before saving: No" in text


def test_report_says_when_no_model_call_was_recorded(tmp_path):
    conn = _case(tmp_path, None)
    store_findings(conn, "CASE-P")

    assert "No model call recorded" in _pdf_text(conn)
