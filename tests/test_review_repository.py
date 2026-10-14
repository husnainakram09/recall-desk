
"""Integration tests for version-bound review records."""

import sqlite3
from dataclasses import replace

import pytest

from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    load_review_decisions,
    record_review_decision,
    store_findings,
)
from storage.review_policy import ReviewAction
from tests.test_repository import NOTICE, STOCK


@pytest.fixture
def ready_case(tmp_path):
    path = tmp_path / "reviews.db"
    conn = connect(path)
    init_db(conn)

    create_case(
        conn,
        "DEMO-REVIEW",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(conn, "DEMO-REVIEW")

    yield conn, path
    conn.close()


def _record(conn, **overrides):
    params = {
        "case_id": "DEMO-REVIEW",
        "revision": 1,
        "row_id": "A",
        "item_index": 0,
        "action": ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "reviewer_label": "Demo Reviewer",
        "role": "Pharmacist",
        "note": "Synthetic demonstration review",
    }
    params.update(overrides)
    return record_review_decision(conn, **params)


def test_valid_decision_persisted(ready_case):
    conn, _ = ready_case

    decision = _record(conn)

    assert decision.revision == 1
    assert decision.action is ReviewAction.ACKNOWLEDGE_CANDIDATE
    assert decision.is_current
    assert decision.reviewer_label == "Demo Reviewer"


def test_decision_survives_reopening(ready_case):
    conn, path = ready_case
    expected = _record(conn)

    reopened = connect(path)
    try:
        assert load_review_decisions(
            reopened, "DEMO-REVIEW"
        ) == (expected,)
    finally:
        reopened.close()


def test_revision_change_marks_history_stale(ready_case):
    conn, _ = ready_case
    _record(conn)

    append_revision(
        conn,
        "DEMO-REVIEW",
        stock_rows=[replace(STOCK, lot_raw="ZZ9TEST")],
    )

    history = load_review_decisions(conn, "DEMO-REVIEW")

    assert len(history) == 1
    assert history[0].revision == 1
    assert history[0].is_current is False


def test_stale_revision_cannot_receive_decision(ready_case):
    conn, _ = ready_case

    append_revision(
        conn,
        "DEMO-REVIEW",
        stock_rows=[replace(STOCK, lot_raw="ZZ9TEST")],
    )

    with pytest.raises(ValueError, match="Stale"):
        _record(conn)


def test_incompatible_action_rejected(ready_case):
    conn, _ = ready_case

    with pytest.raises(ValueError):
        _record(
            conn,
            action=ReviewAction.RECORD_NONMATCH,
        )


def test_technician_cannot_record_decision(ready_case):
    conn, _ = ready_case

    with pytest.raises(PermissionError):
        _record(conn, role="Technician")


def test_missing_finding_rejected(ready_case):
    conn, _ = ready_case

    with pytest.raises(KeyError):
        _record(conn, row_id="DOES-NOT-EXIST")


def test_duplicate_decision_rejected(ready_case):
    conn, _ = ready_case
    _record(conn)

    with pytest.raises(sqlite3.IntegrityError):
        _record(conn)


def test_blank_reviewer_rejected(ready_case):
    conn, _ = ready_case

    with pytest.raises(ValueError):
        _record(conn, reviewer_label="   ")
