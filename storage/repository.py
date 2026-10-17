"""Versioned SQLite persistence for synthetic RecallDesk cases."""

import hashlib
import json
import re
import sqlite3
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum

from contracts import (
    Code,
    Finding,
    InventoryRow,
    LotScope,
    MatchState,
    NoticeItem,
    Strength,
)
from extraction.spans import split_spans
from extraction.validate import appears_verbatim
from matching.engine import classify
from storage.review_policy import (
    ReviewAction,
    validate_review_action,
    validate_review_note,
)

# notice_source_status values on CaseRevision.
SOURCE_VERIFIED = "verified"  # stored text present and its SHA-256 matches
SOURCE_MISSING = "missing"  # no source text stored for this notice version
SOURCE_HASH_MISMATCH = "hash_mismatch"  # stored text no longer matches its hash


@dataclass(frozen=True)
class NoticeSource:
    """Immutable copy of the notice text that a notice version came from.

    Stored once per notice version and never updated, so a reopened case
    shows exactly the excerpts that were cited when it was saved.
    """

    text: str
    sha256: str
    retrieved_at_utc: str  # when the notice was loaded into the app
    origin: str  # "pdf" | "paste" | "fixture"
    span_pages: dict[str, int] = field(default_factory=dict)
    cited_excerpts: dict[str, str] = field(default_factory=dict)  # span id -> line


def make_notice_source(
    text: str,
    *,
    retrieved_at_utc: str,
    origin: str,
    cited_span_ids=(),
    span_pages: dict[str, int] | None = None,
) -> NoticeSource:
    """Snapshot notice text with its hash and the lines its items cite."""
    if not text.strip():
        raise ValueError("Notice source text is empty.")
    lines = {span.id: span.text for span in split_spans(text)}
    unknown = sorted(set(cited_span_ids) - set(lines))
    if unknown:
        raise ValueError(f"Cited spans are not in the source text: {unknown}")
    return NoticeSource(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        retrieved_at_utc=retrieved_at_utc,
        origin=origin,
        span_pages=dict(span_pages or {}),
        # In document order (S2 before S10), as a reader meets them.
        cited_excerpts={
            sid: line for sid, line in lines.items() if sid in set(cited_span_ids)
        },
    )


@dataclass(frozen=True)
class ExtractionProvenance:
    """The model call that produced the notice draft saved with a case.

    Recorded once when the case is created and never updated. A case whose
    notice was drafted by hand has no provenance.
    """

    endpoint: str
    model: str | None
    request_id: str | None
    latency_ms: float
    called_at_utc: str
    # The reviewer changed the model's draft before saving the case.
    edited_before_save: bool


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
    extraction_provenance: ExtractionProvenance | None = None
    change_note: str | None = None  # why this revision was saved
    notice_source: NoticeSource | None = None
    notice_source_status: str = SOURCE_MISSING


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    extraction_provenance: ExtractionProvenance | None = None,
    notice_source: NoticeSource | None = None,
) -> int:
    """Atomically create a case and its first evidence snapshot.

    Without a notice_source the case can be saved and exported, but review
    decisions stay blocked until a source is attached.
    """
    notice_items = tuple(notice_items)
    stock_rows = tuple(stock_rows)
    _validate_records(notice_items, stock_rows)

    if not case_id.strip() or not source_url.strip():
        raise ValueError("Case ID and source URL are required.")
    if notice_source is not None:
        _check_source_covers(notice_source, notice_items)

    timestamp = _timestamp()
    provenance_json = (
        json.dumps(asdict(extraction_provenance), sort_keys=True)
        if extraction_provenance is not None
        else None
    )

    with conn:
        conn.execute(
            """
            INSERT INTO cases (
                case_id, source_url, created_at_utc, extraction_provenance_json
            ) VALUES (?, ?, ?, ?)
            """,
            (case_id, source_url, timestamp, provenance_json),
        )
        _insert_version(
            conn,
            case_id,
            1,
            1,
            1,
            notice_items,
            stock_rows,
            source_verified,
            scope_reviewed,
            timestamp,
            "Case created",
        )
        if notice_source is not None:
            _insert_source(conn, case_id, 1, notice_source)

    return 1


def _insert_version(
    conn,
    case_id,
    revision,
    notice_version,
    stock_version,
    notice_items,
    stock_rows,
    source_verified,
    scope_reviewed,
    timestamp,
    change_note,
):
    conn.execute(
        """
        INSERT INTO case_versions (
            case_id, revision, notice_version, stock_version,
            notice_json, stock_json, source_verified, scope_reviewed,
            created_at_utc, change_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            revision,
            notice_version,
            stock_version,
            _encode(notice_items),
            _encode(stock_rows),
            int(source_verified),
            int(scope_reviewed),
            timestamp,
            change_note,
        ),
    )


def _insert_source(conn, case_id, notice_version, source: NoticeSource):
    conn.execute(
        """
        INSERT INTO notice_sources (
            case_id, notice_version, source_text, sha256, retrieved_at_utc,
            origin, span_pages_json, cited_excerpts_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            notice_version,
            source.text,
            source.sha256,
            source.retrieved_at_utc,
            source.origin,
            json.dumps(source.span_pages, sort_keys=True),
            # Not sort_keys: cited lines keep document order (S2 before S10).
            json.dumps(source.cited_excerpts, ensure_ascii=False),
        ),
    )


def _check_source_covers(
    source: NoticeSource, notice_items, *, identifiers: bool = False
) -> None:
    """Every cited span must exist in the source.

    With identifiers=True (attaching a source to an existing case), every
    lot and code must also appear in it verbatim, so the wrong notice
    cannot be attached. A PL number is checked without its "PL" label.
    """
    lines = {span.id for span in split_spans(source.text)}
    for item in notice_items:
        missing_spans = sorted(set(item.evidence_span_ids) - lines)
        if missing_spans:
            raise ValueError(
                f"Notice item {item.name!r} cites spans not in the source: "
                f"{missing_spans}"
            )
        if not identifiers:
            continue
        values = list(item.lots) + [
            _PL_LABEL.sub("", code.value.strip())
            if code.system == "UK_PL"
            else code.value
            for code in item.codes
        ]
        absent = [value for value in values if not appears_verbatim(value, source.text)]
        if absent:
            raise ValueError(
                f"Identifiers {absent} of {item.name!r} are not in this source text."
            )


_PL_LABEL = re.compile(r"^PL[\s:.]*")


def _load_source(conn, case_id, notice_version):
    record = conn.execute(
        "SELECT * FROM notice_sources WHERE case_id = ? AND notice_version = ?",
        (case_id, notice_version),
    ).fetchone()
    if record is None:
        return None, SOURCE_MISSING
    source = NoticeSource(
        text=record["source_text"],
        sha256=record["sha256"],
        retrieved_at_utc=record["retrieved_at_utc"],
        origin=record["origin"],
        span_pages=json.loads(record["span_pages_json"]),
        cited_excerpts=json.loads(record["cited_excerpts_json"]),
    )
    actual = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
    if actual != source.sha256:
        return None, SOURCE_HASH_MISMATCH
    return source, SOURCE_VERIFIED


def get_revision(
    conn: sqlite3.Connection,
    case_id: str,
    revision: int | None = None,
) -> CaseRevision:
    """Read an existing revision without modifying it."""
    sql = """
        SELECT v.*, c.source_url, c.extraction_provenance_json
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

    source, source_status = _load_source(
        conn, record["case_id"], record["notice_version"]
    )

    return CaseRevision(
        case_id=record["case_id"],
        source_url=record["source_url"],
        revision=record["revision"],
        notice_version=record["notice_version"],
        stock_version=record["stock_version"],
        notice_items=tuple(_notice(item) for item in json.loads(record["notice_json"])),
        stock_rows=tuple(_stock(row) for row in json.loads(record["stock_json"])),
        source_verified=bool(record["source_verified"]),
        scope_reviewed=bool(record["scope_reviewed"]),
        created_at_utc=record["created_at_utc"],
        extraction_provenance=(
            ExtractionProvenance(**json.loads(record["extraction_provenance_json"]))
            if record["extraction_provenance_json"]
            else None
        ),
        change_note=record["change_note"],
        notice_source=source,
        notice_source_status=source_status,
    )


def append_revision(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    notice_items=None,
    stock_rows=None,
    expected_revision: int | None = None,
    source_verified: bool = False,
    scope_reviewed: bool = False,
    change_note: str | None = None,
    _manage_transaction: bool = True,
) -> int:
    """Append new evidence; never modify the previous snapshot.

    Review flags default to false so a new revision cannot
    silently inherit an earlier verification. A changed notice starts a
    new notice version with no stored source, which blocks decisions
    until its source is attached.
    """
    with conn if _manage_transaction else nullcontext():
        previous = get_revision(conn, case_id)

        if expected_revision is not None and previous.revision != expected_revision:
            raise ValueError("Stale revision: reopen the case before editing.")

        new_notice = tuple(
            previous.notice_items if notice_items is None else notice_items
        )
        new_stock = tuple(previous.stock_rows if stock_rows is None else stock_rows)
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
        notice_version = previous.notice_version + int(notice_changed)

        _insert_version(
            conn,
            case_id,
            revision,
            notice_version,
            previous.stock_version + int(stock_changed),
            new_notice,
            new_stock,
            source_verified,
            scope_reviewed,
            _timestamp(),
            change_note,
        )

        # Revised notice items still come from the same source document:
        # carry it forward, re-quoting the lines the new items cite.
        if notice_changed and previous.notice_source is not None:
            cited = {sid for item in new_notice for sid in item.evidence_span_ids}
            try:
                carried = make_notice_source(
                    previous.notice_source.text,
                    retrieved_at_utc=previous.notice_source.retrieved_at_utc,
                    origin=previous.notice_source.origin,
                    cited_span_ids=cited,
                    span_pages=previous.notice_source.span_pages,
                )
            except ValueError:
                carried = None  # new items cite lines the source lacks
            if carried is not None:
                _insert_source(conn, case_id, notice_version, carried)

    return revision


@dataclass(frozen=True)
class StoredFinding:
    """A finding associated with one case revision."""

    case_id: str
    revision: int
    item_index: int
    finding: Finding
    is_current: bool


def store_findings(
    conn: sqlite3.Connection,
    case_id: str,
    revision: int | None = None,
    *,
    _manage_transaction: bool = True,
) -> tuple[StoredFinding, ...]:
    """Classify saved evidence and persist its findings atomically."""
    snapshot = get_revision(conn, case_id, revision)

    if snapshot.revision != get_revision(conn, case_id).revision:
        raise ValueError("Cannot classify a superseded revision.")

    timestamp = _timestamp()

    with conn if _manage_transaction else nullcontext():
        for item_index, item in enumerate(snapshot.notice_items):
            for row in snapshot.stock_rows:
                missing_reviews = tuple(
                    field
                    for field, verified in (
                        ("source_verified", snapshot.source_verified),
                        ("scope_reviewed", snapshot.scope_reviewed),
                    )
                    if not verified
                )

                if missing_reviews:
                    finding = Finding(
                        row_id=row.row_id,
                        state=MatchState.CHECK_INCOMPLETE,
                        matched_fields=(),
                        missing_fields=missing_reviews,
                        conflicting_fields=(),
                        next_evidence=(
                            "Verify the notice source and affected "
                            "lot scope before classification."
                        ),
                        evidence_span_ids=item.evidence_span_ids,
                    )
                else:
                    finding = classify(row, item)

                payload = json.dumps(
                    asdict(finding),
                    default=_enum_default,
                    sort_keys=True,
                )

                conn.execute(
                    """
                    INSERT INTO findings (
                        case_id, revision, row_id, item_index,
                        state, finding_json, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        snapshot.revision,
                        row.row_id,
                        item_index,
                        finding.state.value,
                        payload,
                        timestamp,
                    ),
                )

    return load_findings(conn, case_id, snapshot.revision)


def load_findings(
    conn: sqlite3.Connection,
    case_id: str,
    revision: int | None = None,
) -> tuple[StoredFinding, ...]:
    """Load previously stored findings without recalculation."""
    snapshot = get_revision(conn, case_id, revision)
    latest_revision = get_revision(conn, case_id).revision

    records = conn.execute(
        """
        SELECT *
        FROM findings
        WHERE case_id = ? AND revision = ?
        ORDER BY row_id, item_index
        """,
        (case_id, snapshot.revision),
    ).fetchall()

    results = []

    for record in records:
        data = json.loads(record["finding_json"])

        finding = Finding(
            row_id=data["row_id"],
            state=MatchState(data["state"]),
            matched_fields=tuple(data["matched_fields"]),
            missing_fields=tuple(data["missing_fields"]),
            conflicting_fields=tuple(data["conflicting_fields"]),
            next_evidence=data["next_evidence"],
            evidence_span_ids=tuple(data["evidence_span_ids"]),
            descriptive_differences=tuple(data.get("descriptive_differences", ())),
        )

        results.append(
            StoredFinding(
                case_id=case_id,
                revision=snapshot.revision,
                item_index=record["item_index"],
                finding=finding,
                is_current=(snapshot.revision == latest_revision),
            )
        )

    return tuple(results)


@dataclass(frozen=True)
class StoredReviewDecision:
    """One immutable simulated review event."""

    decision_id: int
    case_id: str
    revision: int
    row_id: str
    item_index: int
    action: ReviewAction
    finding_state: MatchState
    reviewer_label: str
    reviewer_role: str
    note: str
    decided_at_utc: str
    is_current: bool


def record_review_decision(
    conn: sqlite3.Connection,
    case_id: str,
    revision: int,
    row_id: str,
    item_index: int,
    action: ReviewAction,
    reviewer_label: str,
    role: str,
    *,
    note: str = "",
) -> StoredReviewDecision:
    """Record a simulated decision for current reviewed evidence."""
    label = reviewer_label.strip()

    if not label:
        raise ValueError("A demonstration reviewer label is required.")

    snapshot = get_revision(conn, case_id)

    if revision != snapshot.revision:
        raise ValueError("Stale revision: fresh review is required.")

    if not (snapshot.source_verified and snapshot.scope_reviewed):
        raise ValueError("Source and scope review are incomplete.")

    if snapshot.notice_source_status != SOURCE_VERIFIED:
        raise ValueError(
            "The notice source text for this revision is unavailable or failed "
            "its integrity check. Attach the source and re-review before "
            "recording decisions."
        )

    validate_review_note(action, note)

    record = conn.execute(
        """
        SELECT state FROM findings
        WHERE case_id = ? AND revision = ?
          AND row_id = ? AND item_index = ?
        """,
        (case_id, revision, row_id, item_index),
    ).fetchone()

    if record is None:
        raise KeyError("No stored finding exists for this revision.")

    validate_review_action(
        MatchState(record["state"]),
        action,
        role,
    )

    # The SQLite trigger rechecks revision and action validity
    # when the INSERT executes.
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO review_decisions (
                case_id, revision, row_id, item_index,
                action, reviewer_label, reviewer_role,
                note, decided_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                revision,
                row_id,
                item_index,
                action.value,
                label,
                role,
                note,
                _timestamp(),
            ),
        )

    return next(
        decision
        for decision in load_review_decisions(conn, case_id)
        if decision.decision_id == cursor.lastrowid
    )


def load_review_decisions(
    conn: sqlite3.Connection,
    case_id: str,
) -> tuple[StoredReviewDecision, ...]:
    """Return audit history with current/stale status."""
    current_revision = get_revision(conn, case_id).revision

    records = conn.execute(
        """
        SELECT d.*, f.state AS finding_state
        FROM review_decisions AS d
        JOIN findings AS f
          ON f.case_id = d.case_id
         AND f.revision = d.revision
         AND f.row_id = d.row_id
         AND f.item_index = d.item_index
        WHERE d.case_id = ?
        ORDER BY d.decision_id
        """,
        (case_id,),
    ).fetchall()

    return tuple(
        StoredReviewDecision(
            decision_id=record["decision_id"],
            case_id=record["case_id"],
            revision=record["revision"],
            row_id=record["row_id"],
            item_index=record["item_index"],
            action=ReviewAction(record["action"]),
            finding_state=MatchState(record["finding_state"]),
            reviewer_label=record["reviewer_label"],
            reviewer_role=record["reviewer_role"],
            note=record["note"],
            decided_at_utc=record["decided_at_utc"],
            is_current=(record["revision"] == current_revision),
        )
        for record in records
    )


@dataclass(frozen=True)
class CaseSummary:
    """A saved case available for reopening."""

    case_id: str
    source_url: str
    latest_revision: int
    created_at_utc: str


def list_cases(
    conn: sqlite3.Connection,
) -> tuple[CaseSummary, ...]:
    """List saved cases with their latest evidence revisions."""
    records = conn.execute(
        """
        SELECT
            c.case_id,
            c.source_url,
            c.created_at_utc,
            MAX(v.revision) AS latest_revision
        FROM cases AS c
        JOIN case_versions AS v
          ON v.case_id = c.case_id
        GROUP BY c.case_id
        ORDER BY c.created_at_utc DESC, c.case_id
        """
    ).fetchall()

    return tuple(
        CaseSummary(
            case_id=record["case_id"],
            source_url=record["source_url"],
            latest_revision=record["latest_revision"],
            created_at_utc=record["created_at_utc"],
        )
        for record in records
    )


def correct_stock_lot(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    expected_revision: int,
    row_id: str,
    lot_raw: str | None,
    reason: str | None = None,
) -> int:
    """Save a batch correction as a new unverified evidence revision.

    reason records where the corrected batch was read; the PDF shows it with
    the before and after values.
    """
    snapshot = get_revision(conn, case_id)

    if snapshot.revision != expected_revision:
        raise ValueError("Stale revision: reopen the case before editing.")

    if lot_raw is not None and not isinstance(lot_raw, str):
        raise TypeError("Batch code must be text or None.")

    # Empty input means the batch is no longer known.
    new_lot = None if lot_raw is None or not lot_raw.strip() else lot_raw

    target = next(
        (row for row in snapshot.stock_rows if row.row_id == row_id),
        None,
    )
    if target is None:
        raise KeyError(f"Unknown stock row: {row_id}")

    if target.lot_raw == new_lot:
        raise ValueError("Batch code is unchanged.")

    revised_stock = tuple(
        replace(row, lot_raw=new_lot) if row.row_id == row_id else row
        for row in snapshot.stock_rows
    )

    with conn:
        revision = append_revision(
            conn,
            case_id,
            stock_rows=revised_stock,
            expected_revision=expected_revision,
            change_note=(
                f"Batch correction for row {row_id}: "
                f"{target.lot_raw!r} -> {new_lot!r}. "
                f"Reason: {reason.strip() if reason and reason.strip() else 'not recorded'}"
            ),
            _manage_transaction=False,
        )

        store_findings(
            conn,
            case_id,
            revision,
            _manage_transaction=False,
        )

    return revision


def rereview_case(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    expected_revision: int,
) -> int:
    """Record fresh simulated source/scope review for saved evidence.

    The caller must collect both explicit self-attestations. This does
    not authenticate a reviewer or independently verify the source.
    """
    with conn:
        snapshot = get_revision(conn, case_id)

        if snapshot.revision != expected_revision:
            raise ValueError("Stale revision: reopen the case before review.")

        if snapshot.source_verified and snapshot.scope_reviewed:
            raise ValueError("Source and scope are already reviewed.")

        revision = append_revision(
            conn,
            case_id,
            expected_revision=expected_revision,
            source_verified=True,
            scope_reviewed=True,
            change_note="Source and lot scope re-reviewed (self-attested)",
            _manage_transaction=False,
        )
        store_findings(
            conn,
            case_id,
            revision,
            _manage_transaction=False,
        )

    return revision


def attach_notice_source(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    expected_revision: int,
    notice_source: NoticeSource,
) -> int:
    """Recover a case whose notice version has no stored source text.

    The source must contain every cited span and every listed identifier.
    Attaching resets source/scope review, so decisions need a fresh
    re-review. Returns the revision to review next.
    """
    with conn:
        snapshot = get_revision(conn, case_id)
        if snapshot.revision != expected_revision:
            raise ValueError("Stale revision: reopen the case before editing.")
        if snapshot.notice_source_status != SOURCE_MISSING:
            raise ValueError(
                "This notice version already has stored source text. "
                "Save a new case to use a different source."
            )
        _check_source_covers(notice_source, snapshot.notice_items, identifiers=True)
        _insert_source(conn, case_id, snapshot.notice_version, notice_source)

        if not (snapshot.source_verified or snapshot.scope_reviewed):
            return snapshot.revision

        revision = append_revision(
            conn,
            case_id,
            expected_revision=expected_revision,
            change_note="Notice source text attached; re-review required",
            _manage_transaction=False,
        )
        store_findings(conn, case_id, revision, _manage_transaction=False)
    return revision
