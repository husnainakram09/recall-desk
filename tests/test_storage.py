"""SQLite schema and integrity tests."""

import sqlite3

import pytest

from storage.db import connect, init_db


@pytest.fixture
def db():
    conn = connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


def test_schema_has_required_tables(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()

    names = {row["name"] for row in rows}

    assert {
        "cases",
        "case_versions",
        "findings",
        "approvals",
    }.issubset(names)


def test_foreign_keys_are_enabled(db):
    enabled = db.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1


def test_revision_cannot_exist_without_case(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO case_versions (
                case_id, revision, notice_version,
                stock_version, notice_json, stock_json,
                source_verified, scope_reviewed, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "nonexistent-case", 1, 1, 1,
                "{}", "[]", 0, 0,
                "2026-10-14T00:00:00Z",
            ),
        )
