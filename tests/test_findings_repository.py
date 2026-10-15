"""Finding persistence, review gates and revision tests."""

import sqlite3
from dataclasses import replace

import pytest

from contracts import MatchState
from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    load_findings,
    store_findings,
)
from tests.test_repository import NOTICE, STOCK


def _case(tmp_path, *, reviewed=False):
    conn = connect(tmp_path / "case.db")
    init_db(conn)

    create_case(
        conn,
        "CASE-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
        source_verified=reviewed,
        scope_reviewed=reviewed,
    )
    return conn


def test_unverified_case_cannot_generate_exact_candidate(tmp_path):
    conn = _case(tmp_path)

    findings = store_findings(conn, "CASE-001")

    assert len(findings) == 1
    assert findings[0].finding.state is MatchState.CHECK_INCOMPLETE
    assert "source_verified" in findings[0].finding.missing_fields
    assert "scope_reviewed" in findings[0].finding.missing_fields

    conn.close()


def test_reviewed_case_finding_survives_reopen(tmp_path):
    conn = _case(tmp_path, reviewed=True)

    stored = store_findings(conn, "CASE-001")

    assert stored[0].finding.state is MatchState.EXACT_CANDIDATE
    assert stored[0].is_current

    conn.close()

    reopened = connect(tmp_path / "case.db")
    loaded = load_findings(reopened, "CASE-001")

    assert loaded == stored
    assert loaded[0].finding.row_id == "A"

    reopened.close()


def test_descriptive_differences_survive_reopen(tmp_path):
    conn = connect(tmp_path / "case.db")
    init_db(conn)
    create_case(
        conn,
        "CASE-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [replace(STOCK, product_raw="Synth Test Med")],
        source_verified=True,
        scope_reviewed=True,
    )
    stored = store_findings(conn, "CASE-001")
    conn.close()

    reopened = connect(tmp_path / "case.db")
    loaded = load_findings(reopened, "CASE-001")
    reopened.close()

    assert loaded[0].finding.state is MatchState.EXACT_CANDIDATE
    assert loaded[0].finding.descriptive_differences == ("product",)
    assert loaded == stored


def test_new_revision_preserves_old_findings(tmp_path):
    conn = _case(tmp_path, reviewed=True)
    store_findings(conn, "CASE-001")

    changed = replace(STOCK, lot_raw="ZZ9TEST")

    append_revision(
        conn,
        "CASE-001",
        stock_rows=[changed],
        source_verified=True,
        scope_reviewed=True,
    )

    latest = store_findings(conn, "CASE-001")
    previous = load_findings(conn, "CASE-001", 1)

    assert previous[0].finding.state is MatchState.EXACT_CANDIDATE
    assert previous[0].is_current is False

    assert latest[0].finding.state is MatchState.NOT_MATCHED
    assert latest[0].revision == 2
    assert latest[0].is_current is True

    conn.close()


def test_existing_findings_cannot_be_overwritten(tmp_path):
    conn = _case(tmp_path, reviewed=True)

    store_findings(conn, "CASE-001")

    with pytest.raises(sqlite3.IntegrityError):
        store_findings(conn, "CASE-001")

    assert len(load_findings(conn, "CASE-001")) == 1

    conn.close()
