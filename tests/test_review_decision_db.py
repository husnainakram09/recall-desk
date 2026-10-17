"""Database-level integrity tests for simulated review decisions."""

import sqlite3
from dataclasses import replace

import pytest

from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    store_findings,
)
from tests.test_repository import NOTICE, STOCK


@pytest.fixture
def db():
    conn = connect(":memory:")
    init_db(conn)

    create_case(
        conn,
        "CASE-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=True,
        scope_reviewed=True,
    )
    store_findings(conn, "CASE-001")

    yield conn
    conn.close()


def _insert(
    conn,
    *,
    revision=1,
    action="acknowledge_candidate",
    role="Pharmacist",
):
    conn.execute(
        """
        INSERT INTO review_decisions (
            case_id, revision, row_id, item_index,
            action, reviewer_label, reviewer_role,
            note, decided_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "CASE-001",
            revision,
            "A",
            0,
            action,
            "Demo Reviewer",
            role,
            "Synthetic demonstration only",
            "2026-10-14T09:00:00Z",
        ),
    )


def test_valid_decision_is_stored(db):
    _insert(db)

    record = db.execute("SELECT * FROM review_decisions").fetchone()

    assert record["revision"] == 1
    assert record["action"] == "acknowledge_candidate"
    assert record["reviewer_label"] == "Demo Reviewer"


def test_incompatible_action_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, action="record_nonmatch_for_this_notice")


def test_technician_role_rejected_by_database(db):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, role="Technician")


def test_unverified_case_rejected():
    conn = connect(":memory:")
    try:
        init_db(conn)

        create_case(
            conn,
            "CASE-001",
            "https://example.org/synthetic-notice",
            [NOTICE],
            [STOCK],
        )
        store_findings(conn, "CASE-001")

        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn)
    finally:
        conn.close()


def test_stale_revision_cannot_receive_new_decision(db):
    _insert(db)

    append_revision(
        db,
        "CASE-001",
        stock_rows=[replace(STOCK, lot_raw="ZZ9TEST")],
        source_verified=True,
        scope_reviewed=True,
    )

    # Historical record is retained.
    count = db.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]

    assert count == 1

    # Old evidence can no longer receive a new decision.
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, revision=1)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE review_decisions SET note='altered'",
        "DELETE FROM review_decisions",
    ],
)
def test_review_history_is_append_only(db, sql):
    _insert(db)

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        db.execute(sql)


def test_duplicate_decision_rejected(db):
    _insert(db)

    with pytest.raises(sqlite3.IntegrityError):
        _insert(db)
