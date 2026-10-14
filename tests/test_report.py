"""Tests for synthetic RecallDesk PDF evidence reports."""

from dataclasses import replace
from io import BytesIO

import pytest
from pypdf import PdfReader

from contracts import Code
from export import report
from export.report import SAFETY_STATEMENT, build_case_report
from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    correct_stock_lot,
    create_case,
    record_review_decision,
    store_findings,
)
from storage.review_policy import ReviewAction
from tests.test_repository import NOTICE, STOCK


@pytest.fixture
def report_case():
    conn = connect(":memory:")
    init_db(conn)

    create_case(
        conn,
        "REPORT-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(conn, "REPORT-001")

    yield conn
    conn.close()


def _extract_text(pdf_bytes):
    assert pdf_bytes.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_report_contains_saved_evidence(report_case):
    pdf_bytes = build_case_report(report_case, "REPORT-001")
    text = _extract_text(pdf_bytes)

    assert "REPORT-001" in text
    assert "00123" in text
    assert "exact_candidate" in text
    assert "https://example.org/synthetic-notice" in text
    assert SAFETY_STATEMENT in text
    assert "not authenticated professional approval" in text
    assert "No current decision recorded" in text


def test_report_shows_historical_review_after_correction(report_case):
    record_review_decision(
        report_case,
        "REPORT-001",
        1,
        "A",
        0,
        ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "Demo Reviewer",
        "Pharmacist",
        note="Synthetic review",
    )

    correct_stock_lot(
        report_case,
        "REPORT-001",
        expected_revision=1,
        row_id="A",
        lot_raw="ZZ9TEST",
    )

    text = _extract_text(build_case_report(report_case, "REPORT-001"))

    assert "ZZ9TEST" in text
    assert "check_incomplete" in text
    assert "HISTORICAL / STALE" in text
    assert "Demo Reviewer" in text
    assert "acknowledge_candidate" in text
    assert "Simulated review status: No current decision recorded" in text


def test_report_refuses_missing_findings():
    conn = connect(":memory:")
    try:
        init_db(conn)
        create_case(
            conn,
            "INCOMPLETE-001",
            "https://example.org/notice",
            [NOTICE],
            [STOCK],
        )

        with pytest.raises(ValueError, match="findings are incomplete"):
            build_case_report(conn, "INCOMPLETE-001")
    finally:
        conn.close()


def test_report_includes_identifying_conflict_evidence(report_case):
    append_revision(
        report_case,
        "REPORT-001",
        stock_rows=[
            replace(
                STOCK,
                strength=replace(STOCK.strength, value=10),
                manufacturer="Demo Maker",
                holder="Demo Holder",
            )
        ],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(report_case, "REPORT-001")
    text = _extract_text(build_case_report(report_case, "REPORT-001"))
    for value in (
        "20 mg",
        "10 mg",
        "tablet",
        "GTIN: 05012345678906",
        "Pack size: 28",
        "2028-01",
        "Demo Maker",
        "Demo Holder",
        "conflicting_identifiers",
        "Finding source span IDs: S2",
    ):
        assert value in text


def test_report_disambiguates_multi_product_review_history(report_case):
    revised_notice = replace(
        NOTICE, name="Second Demo Product", codes=(Code("GTIN", "09999999999999"),)
    )
    append_revision(
        report_case,
        "REPORT-001",
        notice_items=[NOTICE, revised_notice],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(report_case, "REPORT-001")
    record_review_decision(
        report_case,
        "REPORT-001",
        2,
        "A",
        1,
        ReviewAction.RECORD_NONMATCH,
        "Multi Reviewer",
        "Pharmacist",
        note="Second product checked",
    )
    append_revision(
        report_case,
        "REPORT-001",
        notice_items=[NOTICE],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(report_case, "REPORT-001")
    text = _extract_text(build_case_report(report_case, "REPORT-001"))
    assert "2: Second Demo Product (notice version 2)" in text
    assert "Finding at decision: not_matched_to_this_notice" in text
    assert "Simulated reviewer role: Pharmacist" in text
    assert "HISTORICAL / STALE" in text


def test_report_keeps_literal_markup_and_line_breaks(report_case):
    record_review_decision(
        report_case,
        "REPORT-001",
        1,
        "A",
        0,
        ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "Reviewer <b>name</b>",
        "Pharmacist",
        note='A&B <script>alert("x")</script>\nSecond line',
    )
    text = _extract_text(build_case_report(report_case, "REPORT-001"))
    assert "Reviewer <b>name</b>" in text
    assert 'A&B <script>alert("x")</script>' in text
    assert "Second line" in text


@pytest.mark.parametrize("text", ["Medicine दवा", "Medicine \x00"])
def test_report_blocks_unsupported_text_instead_of_losing_evidence(report_case, text):
    append_revision(
        report_case,
        "REPORT-001",
        stock_rows=[replace(STOCK, product_raw=text)],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(report_case, "REPORT-001")
    with pytest.raises(ValueError, match="unsupported"):
        build_case_report(report_case, "REPORT-001")


def test_report_rejects_changed_selection_revision(report_case):
    correct_stock_lot(
        report_case, "REPORT-001", expected_revision=1, row_id="A", lot_raw="ZZ9TEST"
    )
    with pytest.raises(ValueError, match="revision changed"):
        build_case_report(report_case, "REPORT-001", expected_revision=1)
    assert not report_case.in_transaction


def test_report_does_not_mix_concurrent_revisions(tmp_path, monkeypatch):
    path = tmp_path / "concurrent.db"
    reader = connect(path)
    writer = connect(path)
    try:
        reader.execute("PRAGMA journal_mode=WAL")
        init_db(reader)
        create_case(
            reader,
            "CONCURRENT",
            "https://example.org/demo",
            [NOTICE],
            [STOCK],
            source_verified=True,
            scope_reviewed=True,
        )
        store_findings(reader, "CONCURRENT")
        record_review_decision(
            reader,
            "CONCURRENT",
            1,
            "A",
            0,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
            "Demo Reviewer",
            "Pharmacist",
        )
        original_get = report.get_revision
        changed = False

        def interleaved_get(*args, **kwargs):
            nonlocal changed
            snapshot = original_get(*args, **kwargs)
            if not changed:
                changed = True
                correct_stock_lot(
                    writer,
                    "CONCURRENT",
                    expected_revision=1,
                    row_id="A",
                    lot_raw="ZZ9TEST",
                )
            return snapshot

        monkeypatch.setattr(report, "get_revision", interleaved_get)
        text = _extract_text(build_case_report(reader, "CONCURRENT"))
        assert "Evidence revision: 1" in text
        assert "Batch: 00123" in text
        assert "Finding: exact_candidate" in text
        assert "ZZ9TEST" not in text
        assert "check_incomplete" not in text
        assert "revision 1 - CURRENT" in text
        assert not reader.in_transaction
        assert original_get(writer, "CONCURRENT").revision == 2
    finally:
        reader.close()
        writer.close()


def test_report_preserves_caller_transaction(report_case):
    report_case.execute("BEGIN")
    create_table = "CREATE TABLE caller_work (value TEXT)"
    report_case.execute(create_table)
    report_case.execute("INSERT INTO caller_work VALUES ('pending')")
    before = report_case.total_changes
    build_case_report(report_case, "REPORT-001")
    assert report_case.in_transaction
    assert report_case.total_changes == before
    report_case.rollback()
    assert not report_case.in_transaction


def test_report_rejects_inconsistent_finding_keys(report_case):
    # The guards prevent updates but a damaged/imported payload can be inserted.
    append_revision(
        report_case, "REPORT-001", stock_rows=[replace(STOCK, lot_raw="ZZ9TEST")]
    )
    report_case.execute(
        """INSERT INTO findings
        SELECT case_id, 2, row_id, 9, state, finding_json, created_at_utc
        FROM findings WHERE revision = 1"""
    )
    report_case.commit()
    with pytest.raises(ValueError, match="do not match"):
        build_case_report(report_case, "REPORT-001")


def test_report_many_pages_keep_all_rows_and_footers(report_case):
    rows = [
        replace(
            STOCK,
            row_id=f"ROW-{index:03}",
            location="Synthetic shelf " + "LONGIDENTIFIER" * 25,
        )
        for index in range(15)
    ]
    append_revision(
        report_case,
        "REPORT-001",
        stock_rows=rows,
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(report_case, "REPORT-001")
    pdf = build_case_report(report_case, "REPORT-001")
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) > 2
    text = _extract_text(pdf)
    assert all(f"Stock row ROW-{index:03}" in text for index in range(15))
    for number, page in enumerate(reader.pages, 1):
        page_text = page.extract_text()
        assert f"Page {number}" in page_text
        assert "Not a clinical clearance" in page_text
