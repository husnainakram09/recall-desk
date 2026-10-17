"""Append-only SQLite guards for RecallDesk audit records."""

import sqlite3

AUDIT_TABLES = (
    "cases",
    "case_versions",
    "notice_sources",
    "findings",
    "approvals",
    "review_decisions",
)


def install_append_only_guards(conn: sqlite3.Connection) -> None:
    """Prevent ordinary SQL updates and deletions.

    Table and operation names come exclusively from fixed
    internal constants, never from user input.
    """
    for table in AUDIT_TABLES:
        for operation in ("UPDATE", "DELETE"):
            trigger_name = f"guard_{table}_{operation.lower()}"

            conn.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_name}
                BEFORE {operation} ON {table}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'append-only audit record'
                    );
                END;
                """
            )
