"""Notice source snapshots: stored with the case, verified on read, required for decisions."""

import hashlib
import sqlite3
from dataclasses import replace

import pytest

from storage.db import connect, init_db
from storage.repository import (
    SOURCE_HASH_MISMATCH,
    SOURCE_MISSING,
    SOURCE_VERIFIED,
    append_revision,
    attach_notice_source,
    correct_stock_lot,
    create_case,
    get_revision,
    load_review_decisions,
    make_notice_source,
    record_review_decision,
    rereview_case,
    store_findings,
)
from storage.review_policy import ReviewAction
from tests.test_repository import NOTICE, SOURCE, STOCK


def _case(tmp_path, *, source=SOURCE, reviewed=True, case_id="SRC-1"):
    conn = connect(tmp_path / "src.db")
    init_db(conn)
    create_case(
        conn,
        case_id,
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=reviewed,
        scope_reviewed=reviewed,
        notice_source=source,
    )
    store_findings(conn, case_id)
    return conn


def test_source_round_trips_with_hash_and_cited_excerpts(tmp_path):
    _case(tmp_path).close()

    reopened = connect(tmp_path / "src.db")
    snapshot = get_revision(reopened, "SRC-1")

    assert snapshot.notice_source_status == SOURCE_VERIFIED
    assert snapshot.notice_source == SOURCE
    assert (
        snapshot.notice_source.sha256
        == hashlib.sha256(SOURCE.text.encode("utf-8")).hexdigest()
    )
    assert snapshot.notice_source.cited_excerpts == {
        "S2": "Synthetic Test Medicine 20 mg tablet, GTIN 05012345678906, "
        "batch 00123, pack size 28"
    }


def test_source_cannot_be_rewritten(tmp_path):
    conn = _case(tmp_path)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"), conn:
        conn.execute("UPDATE notice_sources SET source_text = 'edited'")


def test_tampered_source_is_detected_and_blocks_decisions(tmp_path):
    conn = _case(tmp_path)
    conn.execute("DROP TRIGGER guard_notice_sources_update")
    with conn:
        conn.execute("UPDATE notice_sources SET source_text = source_text || 'x'")

    snapshot = get_revision(conn, "SRC-1")
    assert snapshot.notice_source_status == SOURCE_HASH_MISMATCH
    assert snapshot.notice_source is None
    with pytest.raises(ValueError, match="integrity check"):
        record_review_decision(
            conn,
            "SRC-1",
            1,
            "A",
            0,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
            "Demo",
            "Pharmacist",
        )


def test_case_without_source_blocks_decisions_until_attached(tmp_path):
    conn = _case(tmp_path, source=None)
    assert get_revision(conn, "SRC-1").notice_source_status == SOURCE_MISSING

    with pytest.raises(ValueError, match="unavailable"):
        record_review_decision(
            conn,
            "SRC-1",
            1,
            "A",
            0,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
            "Demo",
            "Pharmacist",
        )

    revision = attach_notice_source(
        conn, "SRC-1", expected_revision=1, notice_source=SOURCE
    )
    attached = get_revision(conn, "SRC-1")
    assert revision == 2
    assert attached.notice_source_status == SOURCE_VERIFIED
    assert not (attached.source_verified or attached.scope_reviewed)

    revision = rereview_case(conn, "SRC-1", expected_revision=2)
    decision = record_review_decision(
        conn,
        "SRC-1",
        revision,
        "A",
        0,
        ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "Demo",
        "Pharmacist",
    )
    assert decision.is_current


def test_attaching_a_different_notice_is_rejected(tmp_path):
    conn = _case(tmp_path, source=None)
    wrong = make_notice_source(
        "SYNTHETIC OTHER NOTICE\nOther medicine, GTIN 05099999999999, batch 77777\n",
        retrieved_at_utc="2026-10-17T00:00:00Z",
        origin="paste",
        cited_span_ids=("S2",),
    )

    with pytest.raises(ValueError, match="not in this source text"):
        attach_notice_source(conn, "SRC-1", expected_revision=1, notice_source=wrong)
    assert get_revision(conn, "SRC-1").notice_source_status == SOURCE_MISSING


def test_cited_span_missing_from_source_is_rejected_at_save(tmp_path):
    conn = connect(tmp_path / "bad.db")
    init_db(conn)
    one_line = make_notice_source(
        "Only one line\n", retrieved_at_utc="2026-10-17T00:00:00Z", origin="paste"
    )

    with pytest.raises(ValueError, match="cites spans not in the source"):
        create_case(
            conn,
            "BAD",
            "https://example.org",
            [NOTICE],
            [STOCK],
            notice_source=one_line,
        )


def test_revised_notice_items_keep_the_same_source(tmp_path):
    conn = _case(tmp_path)
    append_revision(
        conn,
        "SRC-1",
        notice_items=[replace(NOTICE, name="Synthetic Test Medicine (edited)")],
    )

    latest = get_revision(conn, "SRC-1")
    assert latest.notice_version == 2
    assert latest.notice_source_status == SOURCE_VERIFIED
    assert latest.notice_source.text == SOURCE.text


def test_correction_records_reason_and_before_after(tmp_path):
    conn = _case(tmp_path)

    correct_stock_lot(
        conn,
        "SRC-1",
        expected_revision=1,
        row_id="A",
        lot_raw="00124",
        reason="Read from blister foil",
    )

    note = get_revision(conn, "SRC-1").change_note
    assert "row A" in note and "'00123' -> '00124'" in note
    assert "Read from blister foil" in note
    assert get_revision(conn, "SRC-1", 1).change_note == "Case created"


@pytest.mark.parametrize("note", ["", "   ", "short"])
def test_evidence_request_needs_a_useful_note(tmp_path, note):
    conn = _case(tmp_path)
    correct_stock_lot(conn, "SRC-1", expected_revision=1, row_id="A", lot_raw=None)
    revision = rereview_case(conn, "SRC-1", expected_revision=2)

    with pytest.raises(ValueError, match="note of at least"):
        record_review_decision(
            conn,
            "SRC-1",
            revision,
            "A",
            0,
            ReviewAction.REQUEST_EVIDENCE,
            "Demo",
            "Pharmacist",
            note=note,
        )
    assert load_review_decisions(conn, "SRC-1") == ()

    saved = record_review_decision(
        conn,
        "SRC-1",
        revision,
        "A",
        0,
        ReviewAction.REQUEST_EVIDENCE,
        "Demo",
        "Pharmacist",
        note="Read the batch on the blister foil.",
    )
    assert saved.note == "Read the batch on the blister foil."


def test_cited_excerpts_keep_document_order_through_storage(tmp_path):
    text = "".join(f"line {n}\n" for n in range(1, 12))
    source = make_notice_source(
        text,
        retrieved_at_utc="2026-10-17T00:00:00Z",
        origin="paste",
        cited_span_ids=("S10", "S2", "S8"),
    )
    assert list(source.cited_excerpts) == ["S2", "S8", "S10"]

    conn = connect(tmp_path / "order.db")
    init_db(conn)
    item = replace(NOTICE, evidence_span_ids=("S10", "S2", "S8"), codes=(), lots=())
    create_case(
        conn, "ORDER", "https://example.org", [item], [STOCK], notice_source=source
    )

    stored = get_revision(conn, "ORDER").notice_source
    assert list(stored.cited_excerpts) == ["S2", "S8", "S10"]
