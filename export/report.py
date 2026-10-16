"""PDF evidence reports for synthetic RecallDesk cases."""

import sqlite3
from collections import Counter
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from storage.repository import (
    get_revision,
    load_findings,
    load_review_decisions,
)

SAFETY_STATEMENT = "No match in checked sources does not establish safety."


def _text(value):
    """Escape literal evidence; fail instead of silently losing glyphs."""
    raw = str(value if value is not None else "Not recorded")
    try:
        raw.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "Saved text contains characters unsupported by the PDF font. "
            "Export is blocked to avoid losing evidence."
        ) from exc
    if any(
        (ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127 for char in raw
    ):
        raise ValueError("Saved text contains unsupported control characters.")
    return (
        escape(raw)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br/>")
        .replace("\t", "    ")
    )


def _field(story, styles, label, value):
    story.append(
        Paragraph(
            f"<b>{_text(label)}:</b> {_text(value)}",
            styles["BodyText"],
        )
    )


def _provenance(story, styles, snapshot):
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Extraction provenance", styles["Heading3"]))
    p = snapshot.extraction_provenance
    if p is None:
        story.append(
            Paragraph(
                "No model call recorded: the notice was drafted manually, or the "
                "case was saved before provenance was recorded.",
                styles["BodyText"],
            )
        )
        return
    _field(story, styles, "Endpoint", p.endpoint)
    _field(story, styles, "Model", p.model or "Not reported")
    _field(story, styles, "Request ID", p.request_id or "Not reported")
    _field(story, styles, "Latency", f"{p.latency_ms:,.0f} ms")
    _field(story, styles, "Called at (UTC)", p.called_at_utc)
    _field(
        story,
        styles,
        "Draft edited by reviewer before saving",
        "Yes" if p.edited_before_save else "No",
    )
    if snapshot.notice_version > 1:
        _field(
            story,
            styles,
            "Notice evidence since extraction",
            f"Revised (notice version {snapshot.notice_version})",
        )


def _footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(
        18 * mm,
        11 * mm,
        "RecallDesk | Synthetic demonstration | Not a clinical clearance",
    )
    canvas.drawRightString(
        A4[0] - 18 * mm,
        11 * mm,
        f"Page {document.page}",
    )
    canvas.restoreState()


def _saved_evidence(conn, case_id, expected_revision):
    """Capture a consistent read snapshot without committing caller work."""
    conn.execute("SAVEPOINT recalldesk_report")
    try:
        snapshot = get_revision(conn, case_id)
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise ValueError("Case revision changed. Reopen it before exporting.")
        findings = load_findings(conn, case_id, snapshot.revision)
        decisions = load_review_decisions(conn, case_id)
        history = {
            decision.revision: get_revision(conn, case_id, decision.revision)
            for decision in decisions
        }
    except Exception:
        conn.execute("ROLLBACK TO recalldesk_report")
        conn.execute("RELEASE recalldesk_report")
        raise
    conn.execute("RELEASE recalldesk_report")
    return snapshot, findings, decisions, history


def _identity_fields(story, styles, record):
    strength = (
        f"{record.strength.value:g} {record.strength.unit}" if record.strength else None
    )
    for label, value in (
        ("Strength", strength),
        ("Form", record.form),
        ("Holder", record.holder),
        ("Pack size", record.pack_size),
        (
            "Product identifiers",
            "; ".join(f"{code.system}: {code.value}" for code in record.codes)
            or "None recorded",
        ),
    ):
        _field(story, styles, label, value)


def build_case_report(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    expected_revision: int | None = None,
) -> bytes:
    """Export saved evidence as of one snapshot, without reclassification.

    Reviews are simulated. Unreviewed and incomplete cases may be exported
    as evidence reports, but missing saved findings block generation.
    """
    snapshot, findings, decisions, history = _saved_evidence(
        conn, case_id, expected_revision
    )

    expected = len(snapshot.notice_items) * len(snapshot.stock_rows)
    if len(findings) != expected:
        raise ValueError("Saved findings are incomplete. Report generation blocked.")

    finding_map = {
        (entry.finding.row_id, entry.item_index): entry.finding for entry in findings
    }
    expected_keys = {
        (row.row_id, index)
        for index in range(len(snapshot.notice_items))
        for row in snapshot.stock_rows
    }
    if set(finding_map) != expected_keys:
        raise ValueError("Saved findings do not match the evidence snapshot.")
    current_decisions = {
        (decision.row_id, decision.item_index): decision
        for decision in decisions
        if decision.revision == snapshot.revision
    }

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="RecallDesk Synthetic Evidence Report",
        author="Redline Agents",
    )

    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    styles["BodyText"].spaceBefore = 0
    styles["BodyText"].spaceAfter = 3
    story = []

    story.append(Paragraph("RecallDesk", styles["Title"]))
    story.append(Paragraph("Synthetic Recall Evidence Report", styles["Heading2"]))
    story.append(Spacer(1, 5 * mm))

    _field(story, styles, "Case ID", snapshot.case_id)
    _field(story, styles, "Evidence revision", snapshot.revision)
    _field(story, styles, "Notice version", snapshot.notice_version)
    _field(story, styles, "Stock version", snapshot.stock_version)
    _field(story, styles, "Revision saved at (UTC)", snapshot.created_at_utc)
    _field(story, styles, "Notice source URL", snapshot.source_url)
    _field(
        story,
        styles,
        "Source check (self-attested)",
        "Recorded" if snapshot.source_verified else "Not recorded",
    )
    _field(
        story,
        styles,
        "Lot scope review (self-attested)",
        "Recorded" if snapshot.scope_reviewed else "Not recorded",
    )

    _provenance(story, styles, snapshot)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Important limitations", styles["Heading2"]))
    story.append(Paragraph(SAFETY_STATEMENT, styles["BodyText"]))
    story.append(
        Paragraph(
            "All stock is synthetic. Reviewer roles and decisions "
            "are simulated, not authenticated professional approval. "
            "This report may include unreviewed or incomplete findings; "
            "export is not approval. The original notice excerpts and source "
            "document hashes are not stored in SQLite; span IDs alone do not "
            "reproduce the source. Extraction provenance identifies the model "
            "call that drafted the notice, not that its output was correct. Consult "
            "the original source before relying on any finding. Local "
            "append-only database guards are not tamper-proof evidence.",
            styles["BodyText"],
        )
    )

    counts = Counter(entry.finding.state.value for entry in findings)
    _field(
        story,
        styles,
        "Saved finding totals",
        "; ".join(f"{state}: {count}" for state, count in sorted(counts.items())),
    )

    for item_index, item in enumerate(snapshot.notice_items):
        story.append(Spacer(1, 5 * mm))
        story.append(
            Paragraph(
                f"Notice product {item_index + 1}: {_text(item.name)}",
                styles["Heading2"],
            )
        )

        _identity_fields(story, styles, item)

        _field(story, styles, "Affected lot scope", item.lot_scope.value)
        _field(story, styles, "Listed lots", ", ".join(item.lots) or "None")
        _field(
            story,
            styles,
            "Source span IDs",
            ", ".join(item.evidence_span_ids) or "None",
        )

        for row in snapshot.stock_rows:
            finding = finding_map.get((row.row_id, item_index))
            if finding is None:
                raise ValueError(f"Missing finding for {row.row_id}, item {item_index}")

            row_story = []
            row_story.append(Spacer(1, 4 * mm))
            row_story.append(
                Paragraph(
                    f"Stock row {_text(row.row_id)}",
                    styles["Heading3"],
                )
            )

            _field(row_story, styles, "Location", row.location)
            _field(row_story, styles, "Product", row.product_raw)
            _identity_fields(row_story, styles, row)
            _field(row_story, styles, "Manufacturer", row.manufacturer)
            _field(row_story, styles, "Batch", row.lot_raw)
            _field(row_story, styles, "Expiry (as recorded)", row.expiry_raw)
            _field(row_story, styles, "Quantity", f"{row.quantity} {row.unit}")
            _field(row_story, styles, "Finding", finding.state.value)
            decision = current_decisions.get((row.row_id, item_index))
            _field(
                row_story,
                styles,
                "Simulated review status",
                f"Recorded: {decision.action.value}"
                if decision
                else "No current decision recorded",
            )
            _field(
                row_story,
                styles,
                "Matched fields",
                ", ".join(finding.matched_fields) or "None",
            )
            _field(
                row_story,
                styles,
                "Missing fields",
                ", ".join(finding.missing_fields) or "None",
            )
            _field(
                row_story,
                styles,
                "Conflicting fields",
                ", ".join(finding.conflicting_fields) or "None",
            )
            _field(
                row_story,
                styles,
                "Next evidence question",
                finding.next_evidence or "None recorded",
            )
            _field(
                row_story,
                styles,
                "Finding source span IDs",
                ", ".join(finding.evidence_span_ids) or "None",
            )

            story.append(KeepTogether(row_story))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Simulated review history", styles["Heading2"]))

    if not decisions:
        story.append(Paragraph("No review decisions recorded.", styles["BodyText"]))

    for decision in decisions:
        status = (
            "CURRENT"
            if decision.revision == snapshot.revision
            else "HISTORICAL / STALE"
        )
        reviewed_item = history[decision.revision].notice_items[decision.item_index]

        decision_story = []
        decision_story.append(Spacer(1, 3 * mm))
        _field(
            decision_story,
            styles,
            "Decision",
            f"Row {decision.row_id}, revision {decision.revision} - {status}",
        )
        _field(
            decision_story,
            styles,
            "Notice product",
            (
                f"{decision.item_index + 1}: {reviewed_item.name} "
                f"(notice version {history[decision.revision].notice_version})"
            ),
        )
        _field(
            decision_story, styles, "Finding at decision", decision.finding_state.value
        )
        _field(decision_story, styles, "Action", decision.action.value)
        _field(decision_story, styles, "Reviewer label", decision.reviewer_label)
        _field(
            decision_story, styles, "Simulated reviewer role", decision.reviewer_role
        )
        _field(decision_story, styles, "Recorded at", decision.decided_at_utc)
        _field(decision_story, styles, "Review note", decision.note or "None")

        story.append(KeepTogether(decision_story))

    document.build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
    )

    return buffer.getvalue()
