
"""Tests for discovering saved cases after application restart."""

from dataclasses import replace

from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    list_cases,
)
from tests.test_repository import NOTICE, STOCK


def test_saved_case_can_be_discovered_after_reopen(tmp_path):
    path = tmp_path / "resume.db"

    conn = connect(path)
    init_db(conn)

    create_case(
        conn,
        "RESUME-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
    )

    append_revision(
        conn,
        "RESUME-001",
        stock_rows=[replace(STOCK, lot_raw="ZZ9TEST")],
    )

    conn.close()

    reopened = connect(path)
    try:
        cases = list_cases(reopened)

        assert len(cases) == 1
        assert cases[0].case_id == "RESUME-001"
        assert cases[0].latest_revision == 2
        assert cases[0].source_url == (
            "https://example.org/synthetic-notice"
        )
    finally:
        reopened.close()


def test_new_database_has_no_saved_cases():
    conn = connect(":memory:")
    try:
        init_db(conn)
        assert list_cases(conn) == ()
    finally:
        conn.close()
