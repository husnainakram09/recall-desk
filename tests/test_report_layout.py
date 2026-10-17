"""PDF structure: summary table, revision history, source appendix, links."""

from dataclasses import replace
from io import BytesIO

from pypdf import PdfReader

from export.report import SAFETY_STATEMENT, build_case_report
from storage.db import connect, init_db
from storage.repository import (
    correct_stock_lot,
    create_case,
    record_review_decision,
    rereview_case,
    store_findings,
)
from storage.review_policy import ReviewAction
from tests.test_repository import NOTICE, SOURCE, STOCK


def _text(pdf):
    return " ".join(
        " ".join(page.extract_text().split()) for page in PdfReader(BytesIO(pdf)).pages
    )


def _case(tmp_path):
    conn = connect(tmp_path / "layout.db")
    init_db(conn)
    other = replace(STOCK, row_id="B", lot_raw="99999")
    create_case(
        conn,
        "LAYOUT-1",
        "https://example.org/synthetic-notice?a=1&b=2",
        [NOTICE],
        [STOCK, other],
        source_verified=True,
        scope_reviewed=True,
        notice_source=SOURCE,
    )
    store_findings(conn, "LAYOUT-1")
    correct_stock_lot(
        conn,
        "LAYOUT-1",
        expected_revision=1,
        row_id="A",
        lot_raw="00124",
        reason="Read from blister foil",
    )
    correct_stock_lot(
        conn,
        "LAYOUT-1",
        expected_revision=2,
        row_id="A",
        lot_raw="00123",
        reason="Rechecked receiving record",
    )
    revision = rereview_case(conn, "LAYOUT-1", expected_revision=3)
    record_review_decision(
        conn,
        "LAYOUT-1",
        revision,
        "A",
        0,
        ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "Demo Reviewer",
        "Pharmacist",
    )
    return conn


def test_front_page_summarises_every_row_with_review_status(tmp_path):
    text = _text(build_case_report(_case(tmp_path), "LAYOUT-1"))

    assert "Findings at a glance" in text
    assert "Simulated reviews: 1 recorded, 1 pending, 0 blocked" in text
    assert "Next action" in text
    assert "Done: candidate acknowledged" in text
    assert "Pharmacist: record non-match for this notice" in text
    assert "Report generated at (UTC)" in text


def test_revision_history_shows_reasons_and_batch_changes(tmp_path):
    text = _text(build_case_report(_case(tmp_path), "LAYOUT-1"))

    assert "Evidence revision history" in text
    assert "Change: Case created" in text
    assert "Read from blister foil" in text
    assert "row A: '00123' -> '00124'" in text
    assert "row A: '00124' -> '00123'" in text
    assert "Source and lot scope re-reviewed (self-attested)" in text


def test_source_appendix_quotes_cited_lines_with_hash(tmp_path):
    text = _text(build_case_report(_case(tmp_path), "LAYOUT-1"))

    assert "Appendix A: notice source snapshot" in text
    assert SOURCE.sha256 in text
    assert "Synthetic Test Medicine 20 mg tablet, GTIN 05012345678906" in text
    assert "Notice source text: Stored and intact" in text


def test_not_matched_rows_are_in_their_own_appendix(tmp_path):
    text = _text(build_case_report(_case(tmp_path), "LAYOUT-1"))

    appendix = text.index("Appendix B: rows not matched to this notice")
    assert text.index("Stock row B") > appendix
    assert text.index("Stock row A") < appendix
    assert SAFETY_STATEMENT in text[appendix:]


def test_source_url_and_endpoint_are_clickable(tmp_path):
    pdf = build_case_report(_case(tmp_path), "LAYOUT-1")

    uris = [
        annot.get_object()["/A"]["/URI"]
        for page in PdfReader(BytesIO(pdf)).pages
        for annot in page.get("/Annots", [])
    ]
    assert "https://example.org/synthetic-notice?a=1&b=2" in uris
