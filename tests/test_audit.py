"""Append-only history protections."""

import sqlite3
from dataclasses import replace

import pytest

from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    get_revision,
    load_findings,
    store_findings,
)
from tests.test_repository import NOTICE, STOCK


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "audit.db")
    init_db(conn)

    create_case(
        conn,
        "AUDIT-001",
        "https://example.org/synthetic",
        [NOTICE],
        [STOCK],
    )

    yield conn
    conn.close()


def test_source_reference_cannot_be_overwritten(db):
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            """
            UPDATE cases
            SET source_url = ?
            WHERE case_id = ?
            """,
            ("https://example.org/changed", "AUDIT-001"),
        )

    assert get_revision(db, "AUDIT-001").source_url == "https://example.org/synthetic"


def test_stock_snapshot_cannot_be_overwritten(db):
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            """
            UPDATE case_versions
            SET stock_json = '[]'
            WHERE case_id = ? AND revision = 1
            """,
            ("AUDIT-001",),
        )

    assert get_revision(db, "AUDIT-001", 1).stock_rows == (STOCK,)


def test_stored_finding_cannot_be_deleted(db):
    store_findings(db, "AUDIT-001")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "DELETE FROM findings WHERE case_id = ?",
            ("AUDIT-001",),
        )

    assert len(load_findings(db, "AUDIT-001")) == 1


def test_new_revision_still_allowed(db):
    # Schema initialization is repeatable.
    init_db(db)

    updated = replace(STOCK, lot_raw="00099")

    assert (
        append_revision(
            db,
            "AUDIT-001",
            stock_rows=[updated],
        )
        == 2
    )

    assert get_revision(db, "AUDIT-001", 1).stock_rows[0].lot_raw == "00123"

    assert get_revision(db, "AUDIT-001", 2).stock_rows[0].lot_raw == "00099"
