"""Local SQLite schema for versioned RecallDesk review cases."""

import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite database with foreign keys enforced."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the minimal versioned case schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_versions (
            case_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            notice_version INTEGER NOT NULL CHECK (notice_version >= 1),
            stock_version INTEGER NOT NULL CHECK (stock_version >= 1),
            notice_json TEXT NOT NULL,
            stock_json TEXT NOT NULL,
            source_verified INTEGER NOT NULL
                CHECK (source_verified IN (0, 1)),
            scope_reviewed INTEGER NOT NULL
                CHECK (scope_reviewed IN (0, 1)),
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (case_id, revision),
            FOREIGN KEY (case_id) REFERENCES cases(case_id)
        );

        CREATE TABLE IF NOT EXISTS findings (
            case_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            row_id TEXT NOT NULL,
            item_index INTEGER NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN (
                    'exact_candidate',
                    'needs_evidence',
                    'conflicting_identifiers',
                    'not_matched_to_this_notice',
                    'check_incomplete'
                )
            ),
            finding_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (
                case_id, revision, row_id, item_index
            ),
            FOREIGN KEY (case_id, revision)
                REFERENCES case_versions(case_id, revision)
        );

        CREATE TABLE IF NOT EXISTS approvals (
            approval_id INTEGER PRIMARY KEY,
            case_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            row_id TEXT NOT NULL,
            item_index INTEGER NOT NULL,
            reviewer_id TEXT NOT NULL,
            reviewer_role TEXT NOT NULL
                CHECK (reviewer_role = 'pharmacist'),
            approved_at_utc TEXT NOT NULL,
            FOREIGN KEY (
                case_id, revision, row_id, item_index
            ) REFERENCES findings(
                case_id, revision, row_id, item_index
            )
        );
        """
    )
