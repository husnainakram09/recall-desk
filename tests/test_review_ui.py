"""Review flow through the real Streamlit app (AppTest), with a fake model adapter.

Covers the hands-on review findings: per-row batch confirmation, notes saved
exactly, source excerpts after reopening, failed calls keeping the draft, and
the edge-case CSV through the upload path.
"""

import sqlite3
from pathlib import Path

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

import app.pages.notice as notice_page
from app.demo_fixtures import FIXTURES_DIR, notice
from extraction.token_factory import CallMeta, ExtractionError

MAIN = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


def _proxy_response():
    spans = notice()[0].spans

    def sid(needle):
        return next(s.id for s in spans if needle in s.text)

    product, batch = sid("Lercanidipine HCl 20mg Tablets"), sid("MD4L07 01/2028")
    return {
        "items": [
            {
                "name": {"value": "Lercanidipine HCl 20mg Tablets", "span": product},
                "strength": {"value": 20, "unit": "mg", "span": product},
                "form": {"value": "Tablets", "span": product},
                "holder": {
                    "value": "Recordati Industria Chimica e Farmaceutica S.p.A.",
                    "span": sid("Recordati Industria"),
                },
                "codes": [
                    {
                        "system": "UK_PL",
                        "value": "04595/0011",
                        "span": sid("PL: 04595"),
                    },
                    {"system": "GTIN", "value": "8057742821983", "span": sid("GTIN:")},
                ],
                "lot_scope": {"value": "explicit_list", "span": batch},
                "lots": [{"value": "MD4L07", "span": batch}],
                "pack_size": {"value": 28, "span": batch},
            }
        ]
    }


class FakeAdapter:
    fail = False

    def __init__(self):
        self.last_call_meta = None

    def extract(self, text):
        self.last_call_meta = CallMeta(
            "https://amd.example.test/v1/chat/completions",
            "2026-10-17T12:00:00Z",
            "req-FAIL" if FakeAdapter.fail else "req-OK",
            1000.0,
            503 if FakeAdapter.fail else 200,
            2 if FakeAdapter.fail else 1,
            "fake-model",
            None,
        )
        if FakeAdapter.fail:
            raise ExtractionError("Endpoint returned HTTP 503 after 2 attempt(s)")
        return _proxy_response()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolates .recalldesk_demo.db
    monkeypatch.setattr(notice_page, "TokenFactoryAdapter", FakeAdapter)
    FakeAdapter.fail = False
    return AppTest.from_file(MAIN, default_timeout=60).run()


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run()


def _prepare_session(at):
    _click(at, "Load synthetic demo stock")
    at.sidebar.selectbox[0].set_value("Notice").run()
    _click(at, "Load MHRA notice EL(25)A/17 (fixture)")
    _click(at, "Run extraction")


def _save_case(at):
    at.sidebar.selectbox[0].set_value("Review").run()
    for box in at.checkbox:
        if box.label.startswith(("I checked this draft", "I reviewed the affected")):
            box.check()
    _click(at, "Save as new case")
    return (
        sqlite3.connect(".recalldesk_demo.db")
        .execute("SELECT case_id FROM cases")
        .fetchone()[0]
    )


def _select_row(at, row_id):
    box = next(s for s in at.selectbox if s.label == "Stock record to inspect")
    box.set_value("ABCDEFGHIJKL".index(row_id)).run()


def _confirm_box(at, row_id):
    return next(
        c
        for c in at.checkbox
        if c.label.startswith(f"I checked the batch evidence for row {row_id}")
    )


def test_batch_confirmation_belongs_to_one_row_and_revision(app):
    _prepare_session(app)
    case_id = _save_case(app)

    # Each row's confirmation lives under its own case/revision/row key and
    # starts unchecked, so a check for one pack cannot appear on another.
    _select_row(app, "C")
    c_box = _confirm_box(app, "C")
    assert c_box.value is False
    assert c_box.key == f"lot_{case_id}_1_C_0_confirmed"

    _select_row(app, "D")
    d_box = _confirm_box(app, "D")
    assert d_box.value is False
    assert d_box.key == f"lot_{case_id}_1_D_0_confirmed"

    # An unchecked save is refused.
    _click(app, "Save correction as new revision")
    assert any("Confirm the batch evidence for row D" in w.value for w in app.warning)

    _select_row(app, "C")
    next(
        t for t in app.text_input if t.label.startswith("Batch code for row C")
    ).set_value("MD4L07")
    next(
        t for t in app.text_input if t.label.startswith("Where was it read")
    ).set_value("Blister foil")
    _confirm_box(app, "C").check()
    _click(app, "Save correction as new revision")

    assert not app.exception
    revision = (
        sqlite3.connect(".recalldesk_demo.db")
        .execute(
            "SELECT MAX(revision) FROM case_versions WHERE case_id = ?", (case_id,)
        )
        .fetchone()[0]
    )
    assert revision == 2
    after = _confirm_box(app, "C")  # revision 2: a fresh, unchecked confirmation
    assert after.key == f"lot_{case_id}_2_C_0_confirmed"
    assert after.value is False


def test_evidence_request_needs_a_note_and_saves_it_exactly(app):
    _prepare_session(app)
    _save_case(app)
    app.sidebar.selectbox(key="role").set_value("Pharmacist").run()
    _select_row(app, "C")  # needs_evidence: lot not recorded

    next(
        t for t in app.text_input if t.label == "Demonstration reviewer label"
    ).set_value("Demo pharmacist")
    _click(app, "Request additional evidence")
    assert any("note of at least" in e.value for e in app.error)
    db = sqlite3.connect(".recalldesk_demo.db")
    assert db.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0

    note = "Read the batch on the blister foil of row C."
    next(
        t for t in app.text_input if t.label == "Demonstration reviewer label"
    ).set_value("Demo pharmacist")
    next(t for t in app.text_area if t.label.startswith("Review note")).set_value(note)
    _click(app, "Request additional evidence")

    assert db.execute("SELECT note FROM review_decisions").fetchone()[0] == note
    assert any(note in s.value for s in app.success)


def test_reopened_case_shows_its_stored_source_excerpts(app):
    _prepare_session(app)
    case_id = _save_case(app)

    fresh = AppTest.from_file(MAIN, default_timeout=60).run()  # a browser refresh
    fresh.sidebar.selectbox[0].set_value("Review").run()
    fresh.radio(key="review_mode").set_value("open").run()

    page = " ".join(m.value for m in fresh.markdown)
    assert case_id in page
    assert "stored and intact" in page
    assert "rd-span rd-cited" in page and "MD4L07 01/2028 28 10/04/2025" in page
    assert not any("not available" in w.value for w in fresh.warning)


def test_failed_extraction_keeps_the_last_good_draft(app):
    _prepare_session(app)
    items_before = app.session_state["notice_items"]

    FakeAdapter.fail = True
    _click(app, "Run extraction")

    assert any("draft is kept" in e.value and "HTTP 503" in e.value for e in app.error)
    assert app.session_state["notice_items"] == items_before
    assert app.session_state["call_meta"].request_id == "req-OK"


def test_edge_case_csv_through_the_upload_path(app, monkeypatch):
    data = (FIXTURES_DIR / "stock_edge_cases.csv").read_bytes()

    class Upload:
        file_id = "edge-cases"

        def getvalue(self):
            return data

    real = streamlit.file_uploader
    monkeypatch.setattr(
        streamlit,
        "file_uploader",
        lambda label, **kw: Upload() if label == "Stock CSV" else real(label, **kw),
    )
    app.run()

    metrics = {m.label: m.value for m in app.metric}
    assert metrics == {"Rows loaded": "12", "Rows with errors": "4"}
    rows = app.session_state["inventory"]
    assert [r.row_id for r in rows][:3] == ["X01", "X02", "X03"]
    assert {r.lot_raw for r in rows if r.row_id in ("X07", "X08")} == {
        "md4l07",
        "MD4LO7",
    }
