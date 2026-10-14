"""User-facing saved-case PDF export behavior in Streamlit."""

from dataclasses import replace
from io import BytesIO

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from app import session
from app.pages import export
from app.pages.review_cases import ACTIVE_KEY
from storage.db import connect, init_db
from storage.repository import create_case, store_findings
from tests.test_repository import NOTICE, STOCK


def _render_export():
    from app.pages.export import render

    render()


@pytest.fixture
def export_database(tmp_path, monkeypatch):
    path = tmp_path / "demo.db"
    monkeypatch.setattr(export, "DB_PATH", path)
    return path


def _save_case(path, case_id, *, findings=True, reviewed=True):
    conn = connect(path)
    try:
        init_db(conn)
        create_case(
            conn,
            case_id,
            "https://example.org/saved-notice",
            [NOTICE],
            [STOCK],
            source_verified=reviewed,
            scope_reviewed=reviewed,
        )
        if findings:
            store_findings(conn, case_id)
    finally:
        conn.close()


@pytest.fixture
def downloads(monkeypatch):
    """Capture download payloads because AppTest exposes only media URLs."""
    import streamlit as st

    captured = []
    original = st.download_button

    def capture(label, data, **kwargs):
        captured.append({"data": data, **kwargs})
        return original(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    return captured


@pytest.mark.parametrize("existing_database", [False, True])
def test_export_without_saved_cases_is_guided(export_database, existing_database):
    if existing_database:
        conn = connect(export_database)
        init_db(conn)
        conn.close()

    page = AppTest.from_function(_render_export).run()

    assert not page.exception
    assert "Save a synthetic case" in page.info[0].value
    assert not page.selectbox
    assert not page.button
    assert not page.get("download_button")


def test_export_requires_selection_when_active_case_is_absent(export_database):
    _save_case(export_database, "SAVED-001")
    page = AppTest.from_function(_render_export)
    page.session_state[ACTIVE_KEY] = "NO-LONGER-PRESENT"
    page.run()

    assert not page.exception
    assert page.selectbox[0].value is None
    assert not page.button
    assert not page.get("download_button")


def test_download_contains_saved_evidence_and_safe_filename(
    export_database, downloads
):
    case_id = "../SAVED:001"
    _save_case(export_database, case_id)
    page = AppTest.from_function(_render_export)
    page.session_state[ACTIVE_KEY] = case_id
    page.session_state[session.INVENTORY] = [
        replace(STOCK, lot_raw="UNSAVED-LOT", product_raw="Unsaved medicine")
    ]
    page.session_state[session.NOTICE_ITEMS] = [
        replace(NOTICE, name="Unsaved notice", lots=("UNSAVED-LOT",))
    ]
    page.run()

    assert not page.exception
    assert page.selectbox[0].value == case_id
    assert not page.get("download_button")

    page.button[0].click().run()

    assert not page.exception
    assert not page.error
    assert len(page.get("download_button")) == 1
    assert len(downloads) == 1
    payload = downloads[0]
    assert payload["mime"] == "application/pdf"
    assert payload["file_name"] == "recalldesk-___SAVED_001-r1.pdf"
    assert payload["data"].startswith(b"%PDF-")
    text = "\n".join(
        sheet.extract_text() for sheet in PdfReader(BytesIO(payload["data"])).pages
    )
    assert case_id in text
    assert "00123" in text
    assert "https://example.org/saved-notice" in text
    assert "UNSAVED-LOT" not in text
    assert "Unsaved medicine" not in text
    assert "Unsaved notice" not in text


def test_changing_selection_requires_preparing_a_fresh_report(
    export_database, downloads
):
    _save_case(export_database, "SAVED-001")
    _save_case(export_database, "SAVED-002")
    page = AppTest.from_function(_render_export)
    page.session_state[ACTIVE_KEY] = "SAVED-001"
    page.run().button[0].click().run()

    assert not page.exception
    assert len(page.get("download_button")) == 1

    page.selectbox[0].select("SAVED-002").run()

    assert not page.exception
    assert "SAVED-002" in page.info[0].value
    assert not page.get("download_button")
    assert len(downloads) == 1


def test_export_refuses_missing_saved_findings(export_database, downloads):
    _save_case(export_database, "INCOMPLETE-001", findings=False)
    page = AppTest.from_function(_render_export)
    page.session_state[ACTIVE_KEY] = "INCOMPLETE-001"
    page.run().button[0].click().run()

    assert not page.exception
    assert "findings are incomplete" in page.error[0].value
    assert not page.get("download_button")
    assert not downloads


def test_unreviewed_export_warns_and_retains_status(export_database, downloads):
    _save_case(export_database, "UNREVIEWED-001", reviewed=False)
    page = AppTest.from_function(_render_export)
    page.session_state[ACTIVE_KEY] = "UNREVIEWED-001"
    page.run().button[0].click().run()

    assert not page.exception
    assert any("review is incomplete" in warning.value for warning in page.warning)
    assert len(page.get("download_button")) == 1
    text = "\n".join(
        sheet.extract_text()
        for sheet in PdfReader(BytesIO(downloads[0]["data"])).pages
    )
    assert "check_incomplete" in text
    assert "Source check (self-attested): Not recorded" in text
    assert "Lot scope review (self-attested): Not recorded" in text
    assert "No match in checked sources does not establish safety." in text
