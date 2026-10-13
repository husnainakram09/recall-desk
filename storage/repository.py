"""Versioned SQLite persistence for synthetic RecallDesk cases."""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum

from contracts import Code, InventoryRow, LotScope, NoticeItem, Strength


@dataclass(frozen=True)
class CaseRevision:
    case_id: str
    source_url: str
    revision: int
    notice_version: int
    stock_version: int
    notice_items: tuple[NoticeItem, ...]
    stock_rows: tuple[InventoryRow, ...]
    source_verified: bool
    scope_reviewed: bool
    created_at_utc: str


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _enum_default(value):
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot encode {type(value).__name__}")


def _encode(records) -> str:
    return json.dumps(
        [asdict(record) for record in records],
        default=_enum_default,
        sort_keys=True,
        ensure_ascii=False,
    )


def _strength(value):
    return Strength(**value) if value is not None else None


def _notice(value):
    return NoticeItem(
        name=value["name"],
        strength=_strength(value["strength"]),
        form=value["form"],
        holder=value["holder"],
        codes=tuple(Code(**code) for code in value["codes"]),
        lot_scope=LotScope(value["lot_scope"]),
        lots=tuple(value["lots"]),
        pack_size=value["pack_size"],
        evidence_span_ids=tuple(value["evidence_span_ids"]),
    )


def _stock(value):
    return InventoryRow(
        row_id=value["row_id"],
        location=value["location"],
        product_raw=value["product_raw"],
        strength=_strength(value["strength"]),
        form=value["form"],
        manufacturer=value["manufacturer"],
        holder=value["holder"],
        lot_raw=value["lot_raw"],
        expiry_raw=value["expiry_raw"],
        pack_size=value["pack_size"],
        codes=tuple(Code(**code) for code in value["codes"]),
        quantity=value["quantity"],
        unit=value["unit"],
    )


def _validate_records(notice_items, stock_rows):
    if not notice_items or not stock_rows:
        raise ValueError("A case needs notice items and stock rows.")

    ids = [row.row_id for row in stock_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate inventory row IDs are not allowed.")


def create_case(
    conn: sqlite3.Connection,
    case_id: str,
    source_url: str,
    notice_items,
    stock_rows,
    *,
    source_verified: bool = False,
    scope_reviewed: bool = False,
) -> int:
    """Atomically create a case and its first evidence snapshot."""
    notice_items = tuple(notice_items)
    stock_rows = tuple(stock_rows)
    _validate_records(notice_items, stock_rows)

    if not case_id.strip() or not source_url.strip():
        raise ValueError("Case ID and source URL are required.")

    timestamp = _timestamp()

    with conn:
        conn.execute(
            "INSERT INTO cases VALUES (?, ?, ?)",
            (case_id, source_url, timestamp),
        )
        conn.execute(
            """
            INSERT INTO case_versions VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id, 1, 1, 1,
                _encode(notice_items),
                _encode(stock_rows),
                int(source_verified),
                int(scope_reviewed),
                timestamp,
            ),
        )

    return 1


def get_revision(
    conn: sqlite3.Connection,
    case_id: str,
    revision: int | None = None,
) -> CaseRevision:
    """Read an existing revision without modifying it."""
    sql = """
        SELECT v.*, c.source_url
        FROM case_versions AS v
        JOIN cases AS c ON c.case_id = v.case_id
        WHERE v.case_id = ?
    """
    params = [case_id]

    if revision is not None:
        sql += " AND v.revision = ?"
        params.append(revision)

    sql += " ORDER BY v.revision DESC LIMIT 1"

    record = conn.execute(sql, params).fetchone()
    if record is None:
        raise KeyError(f"Case revision not found: {case_id}, {revision}")

    return CaseRevision(
        case_id=record["case_id"],
        source_url=record["source_url"],
        revision=record["revision"],
        notice_version=record["notice_version"],
        stock_version=record["stock_version"],
        notice_items=tuple(
            _notice(item)
            for item in json.loads(record["notice_json"])
        ),
        stock_rows=tuple(
            _stock(row)
            for row in json.loads(record["stock_json"])
        ),
        source_verified=bool(record["source_verified"]),
        scope_reviewed=bool(record["scope_reviewed"]),
        created_at_utc=record["created_at_utc"],
    )


def append_revision(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    notice_items=None,
    stock_rows=None,
    source_verified: bool = False,
    scope_reviewed: bool = False,
) -> int:
    """Append new evidence; never modify the previous snapshot.

    Review flags default to false so a new revision cannot
    silently inherit an earlier verification.
    """
    with conn:
        previous = get_revision(conn, case_id)

        new_notice = tuple(
            previous.notice_items if notice_items is None
            else notice_items
        )
        new_stock = tuple(
            previous.stock_rows if stock_rows is None
            else stock_rows
        )
        _validate_records(new_notice, new_stock)

        notice_changed = new_notice != previous.notice_items
        stock_changed = new_stock != previous.stock_rows
        review_changed = (
            source_verified != previous.source_verified
            or scope_reviewed != previous.scope_reviewed
        )

        if not (notice_changed or stock_changed or review_changed):
            raise ValueError("No new evidence or review changes.")

        revision = previous.revision + 1

        conn.execute(
            """
            INSERT INTO case_versions VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                revision,
                previous.notice_version + int(notice_changed),
                previous.stock_version + int(stock_changed),
                _encode(new_notice),
                _encode(new_stock),
                int(source_verified),
                int(scope_reviewed),
                _timestamp(),
            ),
        )

    return revision
