"""Local SQLite schema for versioned RecallDesk review cases."""

import sqlite3
from pathlib import Path

from storage.audit import install_append_only_guards


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


        CREATE TABLE IF NOT EXISTS review_decisions (
            decision_id INTEGER PRIMARY KEY,
            case_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            row_id TEXT NOT NULL,
            item_index INTEGER NOT NULL,
            action TEXT NOT NULL,
            reviewer_label TEXT NOT NULL
              CHECK (length(trim(reviewer_label)) > 0),
            reviewer_role TEXT NOT NULL
              CHECK (reviewer_role = 'Pharmacist'),
            note TEXT NOT NULL DEFAULT '',
            decided_at_utc TEXT NOT NULL,

        UNIQUE (case_id, revision, row_id, item_index),

        FOREIGN KEY (case_id, revision, row_id, item_index)
        REFERENCES findings (
            case_id, revision, row_id, item_index
        )
        );

        CREATE TRIGGER IF NOT EXISTS validate_review_decision
        BEFORE INSERT ON review_decisions
        WHEN NOT EXISTS (
        SELECT 1
        FROM findings AS f
        JOIN case_versions AS v
        ON v.case_id = f.case_id
        AND v.revision = f.revision
        WHERE f.case_id = NEW.case_id
        AND f.revision = NEW.revision
        AND f.row_id = NEW.row_id
        AND f.item_index = NEW.item_index
        AND v.source_verified = 1
        AND v.scope_reviewed = 1
        AND v.revision = (
          SELECT MAX(revision)
          FROM case_versions
          WHERE case_id = NEW.case_id
        )
        AND (
          (f.state = 'exact_candidate'
           AND NEW.action = 'acknowledge_candidate')
        OR (f.state = 'needs_evidence'
           AND NEW.action = 'request_evidence')
        OR (f.state = 'conflicting_identifiers'
           AND NEW.action = 'escalate_conflict')
        OR (f.state = 'not_matched_to_this_notice'
           AND NEW.action = 'record_nonmatch_for_this_notice')
        )
        )
        BEGIN
        SELECT RAISE(
        ABORT,
           'invalid or stale simulated review decision'
        );
        END;


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

    install_append_only_guards(conn)
