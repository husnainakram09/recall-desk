"""Integration tests for version-bound review records."""

import sqlite3
from dataclasses import replace

import pytest

from contracts import MatchState
from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    correct_stock_lot,
    create_case,
    get_revision,
    load_findings,
    load_review_decisions,
    record_review_decision,
    rereview_case,
    store_findings,
)
from storage.review_policy import ReviewAction
from tests.test_repository import NOTICE, SOURCE, STOCK


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
        notice_source=SOURCE,
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
        assert load_review_decisions(reopened, "DEMO-REVIEW") == (expected,)
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


def test_corrected_lot_creates_new_revision(ready_case):
    conn, _ = ready_case

    _record(conn)

    revision = correct_stock_lot(
        conn,
        "DEMO-REVIEW",
        expected_revision=1,
        row_id="A",
        lot_raw="ZZ9TEST",
    )

    old = get_revision(conn, "DEMO-REVIEW", 1)
    new = get_revision(conn, "DEMO-REVIEW")

    assert revision == 2
    assert old.stock_rows[0].lot_raw == STOCK.lot_raw
    assert new.stock_rows[0].lot_raw == "ZZ9TEST"
    assert new.stock_version == 2
    assert not new.source_verified
    assert not new.scope_reviewed

    finding = load_findings(conn, "DEMO-REVIEW")[0].finding
    assert finding.state is MatchState.CHECK_INCOMPLETE

    history = load_review_decisions(conn, "DEMO-REVIEW")
    assert len(history) == 1
    assert history[0].is_current is False


def test_stale_stock_edit_rejected(ready_case):
    conn, _ = ready_case

    correct_stock_lot(
        conn,
        "DEMO-REVIEW",
        expected_revision=1,
        row_id="A",
        lot_raw="ZZ9TEST",
    )

    with pytest.raises(ValueError, match="Stale"):
        correct_stock_lot(
            conn,
            "DEMO-REVIEW",
            expected_revision=1,
            row_id="A",
            lot_raw="MD4L08",
        )


def test_unknown_stock_row_rejected(ready_case):
    conn, _ = ready_case

    with pytest.raises(KeyError):
        correct_stock_lot(
            conn,
            "DEMO-REVIEW",
            expected_revision=1,
            row_id="UNKNOWN",
            lot_raw="ZZ9TEST",
        )


def test_unchanged_batch_rejected(ready_case):
    conn, _ = ready_case

    with pytest.raises(ValueError, match="unchanged"):
        correct_stock_lot(
            conn,
            "DEMO-REVIEW",
            expected_revision=1,
            row_id="A",
            lot_raw=STOCK.lot_raw,
        )


def test_stock_correction_rolls_back_if_findings_fail(
    ready_case,
    monkeypatch,
):
    conn, _ = ready_case
    _record(conn)

    def fail_to_store(*args, **kwargs):
        raise RuntimeError("Simulated finding-storage failure")

    monkeypatch.setattr(
        "storage.repository.store_findings",
        fail_to_store,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated finding-storage failure",
    ):
        correct_stock_lot(
            conn,
            "DEMO-REVIEW",
            expected_revision=1,
            row_id="A",
            lot_raw="ZZ9TEST",
        )

    # No partially saved revision should survive.
    assert get_revision(conn, "DEMO-REVIEW").revision == 1

    # The original decision must remain current.
    history = load_review_decisions(conn, "DEMO-REVIEW")
    assert len(history) == 1
    assert history[0].is_current


def test_rereview_restores_findings_without_changing_evidence(ready_case):
    conn, path = ready_case
    _record(conn)
    correct_stock_lot(
        conn,
        "DEMO-REVIEW",
        expected_revision=1,
        row_id="A",
        lot_raw="ZZ9TEST",
    )
    before = get_revision(conn, "DEMO-REVIEW")

    revision = rereview_case(conn, "DEMO-REVIEW", expected_revision=2)

    reopened = connect(path)
    try:
        reviewed = get_revision(reopened, "DEMO-REVIEW")
        assert revision == reviewed.revision == 3
        assert reviewed.source_verified and reviewed.scope_reviewed
        assert reviewed.notice_items == before.notice_items
        assert reviewed.stock_rows == before.stock_rows
        assert reviewed.notice_version == before.notice_version
        assert reviewed.stock_version == before.stock_version
        assert load_findings(reopened, "DEMO-REVIEW")[0].finding.state is (
            MatchState.NOT_MATCHED
        )
        assert load_findings(reopened, "DEMO-REVIEW", 2)[0].finding.state is (
            MatchState.CHECK_INCOMPLETE
        )
        history = load_review_decisions(reopened, "DEMO-REVIEW")
        assert len(history) == 1
        assert history[0].revision == 1
        assert not history[0].is_current
        assert _record(
            reopened, revision=3, action=ReviewAction.RECORD_NONMATCH
        ).is_current
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("source_verified", "scope_reviewed"),
    [(False, False), (True, False), (False, True)],
)
def test_rereview_renews_both_flags(ready_case, source_verified, scope_reviewed):
    conn, _ = ready_case
    append_revision(
        conn,
        "DEMO-REVIEW",
        source_verified=source_verified,
        scope_reviewed=scope_reviewed,
    )
    store_findings(conn, "DEMO-REVIEW")

    rereview_case(conn, "DEMO-REVIEW", expected_revision=2)

    reviewed = get_revision(conn, "DEMO-REVIEW")
    assert reviewed.source_verified and reviewed.scope_reviewed
    assert load_findings(conn, "DEMO-REVIEW")[0].finding.state is (
        MatchState.EXACT_CANDIDATE
    )


def test_rereview_rejects_complete_revision_without_writes(ready_case):
    conn, _ = ready_case
    before = conn.total_changes

    with pytest.raises(ValueError, match="already reviewed"):
        rereview_case(conn, "DEMO-REVIEW", expected_revision=1)

    assert conn.total_changes == before
    assert get_revision(conn, "DEMO-REVIEW").revision == 1


def test_rereview_rejects_concurrently_changed_revision(ready_case):
    conn, path = ready_case
    second = connect(path)
    try:
        correct_stock_lot(
            second,
            "DEMO-REVIEW",
            expected_revision=1,
            row_id="A",
            lot_raw="ZZ9TEST",
        )
    finally:
        second.close()

    with pytest.raises(ValueError, match="Stale"):
        rereview_case(conn, "DEMO-REVIEW", expected_revision=1)

    assert get_revision(conn, "DEMO-REVIEW").revision == 2
    assert not get_revision(conn, "DEMO-REVIEW").source_verified


def test_rereview_rolls_back_if_findings_fail(ready_case, monkeypatch):
    conn, _ = ready_case
    _record(conn)
    correct_stock_lot(
        conn,
        "DEMO-REVIEW",
        expected_revision=1,
        row_id="A",
        lot_raw="ZZ9TEST",
    )
    before = get_revision(conn, "DEMO-REVIEW")

    def fail_to_store(*args, **kwargs):
        raise RuntimeError("Simulated finding-storage failure")

    monkeypatch.setattr("storage.repository.store_findings", fail_to_store)
    with pytest.raises(RuntimeError, match="finding-storage failure"):
        rereview_case(conn, "DEMO-REVIEW", expected_revision=2)

    assert get_revision(conn, "DEMO-REVIEW") == before
    assert len(load_findings(conn, "DEMO-REVIEW")) == 1
    assert load_findings(conn, "DEMO-REVIEW")[0].finding.state is (
        MatchState.CHECK_INCOMPLETE
    )
    history = load_review_decisions(conn, "DEMO-REVIEW")
    assert len(history) == 1
    assert history[0].revision == 1
