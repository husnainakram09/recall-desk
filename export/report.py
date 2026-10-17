"""PDF evidence reports for synthetic RecallDesk cases."""

import sqlite3
from collections import Counter
from datetime import UTC, datetime
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from contracts import MatchState
from storage.repository import (
    SOURCE_HASH_MISMATCH,
    SOURCE_VERIFIED,
    get_revision,
    load_findings,
    load_review_decisions,
)
from storage.review_policy import ReviewAction

SAFETY_STATEMENT = "No match in checked sources does not establish safety."

_LINK_COLOUR = "#1F5F8B"

_PENDING_ACTION = {
    MatchState.EXACT_CANDIDATE: "Pharmacist: acknowledge candidate",
    MatchState.NEEDS_EVIDENCE: "Pharmacist: request evidence",
    MatchState.CONFLICTING_IDENTIFIERS: "Pharmacist: escalate conflict",
    MatchState.NOT_MATCHED: "Pharmacist: record non-match for this notice",
    MatchState.CHECK_INCOMPLETE: "Complete source and lot scope review",
}
_STATE_LABEL = {
    MatchState.EXACT_CANDIDATE: "Exact candidate",
    MatchState.NEEDS_EVIDENCE: "Needs evidence",
    MatchState.CONFLICTING_IDENTIFIERS: "Conflicting identifiers",
    MatchState.NOT_MATCHED: "Not matched to this notice",
    MatchState.CHECK_INCOMPLETE: "Check incomplete",
}
_ACTION_LABEL = {
    ReviewAction.ACKNOWLEDGE_CANDIDATE: "candidate acknowledged",
    ReviewAction.REQUEST_EVIDENCE: "evidence requested",
    ReviewAction.ESCALATE_CONFLICT: "conflict escalated",
    ReviewAction.RECORD_NONMATCH: "non-match recorded",
}


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


def _link(url):
    """A clickable link for http(s) URLs; other text is shown escaped."""
    if (
        isinstance(url, str)
        and url.startswith(("https://", "http://"))
        and " " not in url
    ):
        return f'<a href="{_text(url)}" color="{_LINK_COLOUR}">{_text(url)}</a>'
    return _text(url)


def _field(story, styles, label, value, *, link=False):
    story.append(
        Paragraph(
            f"<b>{_text(label)}:</b> {_link(value) if link else _text(value)}",
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
    _field(story, styles, "Endpoint", p.endpoint, link=True)
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
        # Every revision up to the exported one, for decisions and history.
        history = {
            revision: get_revision(conn, case_id, revision)
            for revision in range(1, snapshot.revision + 1)
        }
    except Exception:
        conn.execute("ROLLBACK TO recalldesk_report")
        conn.execute("RELEASE recalldesk_report")
        raise
    conn.execute("RELEASE recalldesk_report")
    decisions = tuple(d for d in decisions if d.revision <= snapshot.revision)
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


def _styles():
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    styles["BodyText"].spaceBefore = 0
    styles["BodyText"].spaceAfter = 3
    for name in ("Heading2", "Heading3"):
        styles[name].keepWithNext = 1  # never strand a heading at a page end
    styles.add(
        ParagraphStyle("Cell", parent=styles["BodyText"], fontSize=7.5, leading=9.5)
    )
    styles.add(
        ParagraphStyle(
            "CellHead",
            parent=styles["BodyText"],
            fontSize=7.5,
            leading=9.5,
            fontName="Helvetica-Bold",
        )
    )
    return styles


def _review_status(finding, decision, snapshot):
    if decision is not None:
        return "Recorded", f"Done: {_ACTION_LABEL[decision.action]}"
    if finding.state is MatchState.CHECK_INCOMPLETE:
        return "Blocked", _PENDING_ACTION[finding.state]
    if snapshot.notice_source_status != SOURCE_VERIFIED:
        return "Blocked", "Attach notice source text, then re-review"
    return "Pending", _PENDING_ACTION[finding.state]


def _summary_table(story, styles, snapshot, finding_map, current_decisions):
    widths = [12 * mm, 40 * mm, 24 * mm, 34 * mm, 18 * mm, 46 * mm]
    head = ["Row", "Product (as recorded)", "Batch", "Finding", "Review", "Next action"]
    for item_index, item in enumerate(snapshot.notice_items):
        if len(snapshot.notice_items) > 1:
            story.append(
                Paragraph(
                    f"<b>Against notice product {item_index + 1}:</b> {_text(item.name)}",
                    styles["BodyText"],
                )
            )
        data = [[Paragraph(h, styles["CellHead"]) for h in head]]
        for row in snapshot.stock_rows:
            finding = finding_map[(row.row_id, item_index)]
            status, next_action = _review_status(
                finding, current_decisions.get((row.row_id, item_index)), snapshot
            )
            data.append(
                [
                    Paragraph(_text(row.row_id), styles["Cell"]),
                    Paragraph(_text(row.product_raw), styles["Cell"]),
                    Paragraph(_text(row.lot_raw), styles["Cell"]),
                    Paragraph(_text(_STATE_LABEL[finding.state]), styles["Cell"]),
                    Paragraph(_text(status), styles["Cell"]),
                    Paragraph(_text(next_action), styles["Cell"]),
                ]
            )
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F5")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DDE4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 2 * mm))


def _row_detail(styles, row, finding, decision):
    row_story = [Spacer(1, 4 * mm)]
    row_story.append(Paragraph(f"Stock row {_text(row.row_id)}", styles["Heading3"]))
    _field(row_story, styles, "Location", row.location)
    _field(row_story, styles, "Product", row.product_raw)
    _identity_fields(row_story, styles, row)
    _field(row_story, styles, "Manufacturer", row.manufacturer)
    _field(row_story, styles, "Batch", row.lot_raw)
    _field(row_story, styles, "Expiry (as recorded)", row.expiry_raw)
    _field(row_story, styles, "Quantity", f"{row.quantity} {row.unit}")
    _field(row_story, styles, "Finding", finding.state.value)
    _field(
        row_story,
        styles,
        "Simulated review status",
        f"Recorded: {decision.action.value}"
        if decision
        else "No current decision recorded",
    )
    _field(
        row_story, styles, "Matched fields", ", ".join(finding.matched_fields) or "None"
    )
    _field(
        row_story, styles, "Missing fields", ", ".join(finding.missing_fields) or "None"
    )
    _field(
        row_story,
        styles,
        "Conflicting fields",
        ", ".join(finding.conflicting_fields) or "None",
    )
    if finding.descriptive_differences:
        _field(
            row_story,
            styles,
            "Wording differs from notice (informational)",
            ", ".join(finding.descriptive_differences),
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
    return KeepTogether(row_story)


def _revision_history(story, styles, history):
    story.append(Spacer(1, 5 * mm))
    previous = None
    for revision in sorted(history):
        snap = history[revision]
        entry = [Spacer(1, 2 * mm)]
        if previous is None:  # the heading stays on the page of its first entry
            entry = [Paragraph("Evidence revision history", styles["Heading2"])]
        _field(
            entry,
            styles,
            f"Revision {revision}",
            f"saved {snap.created_at_utc}; source check "
            f"{'recorded' if snap.source_verified else 'not recorded'}; scope review "
            f"{'recorded' if snap.scope_reviewed else 'not recorded'}",
        )
        _field(entry, styles, "Change", snap.change_note or "Not recorded")
        if previous is not None:
            before = {row.row_id: row.lot_raw for row in previous.stock_rows}
            changes = [
                f"row {row.row_id}: {before.get(row.row_id)!r} -> {row.lot_raw!r}"
                for row in snap.stock_rows
                if row.row_id in before and before[row.row_id] != row.lot_raw
            ]
            if changes:
                _field(entry, styles, "Batch before -> after", "; ".join(changes))
        story.append(KeepTogether(entry))
        previous = snap


def _source_appendix(story, styles, snapshot):
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Appendix A: notice source snapshot", styles["Heading2"]))
    if snapshot.notice_source_status == SOURCE_HASH_MISMATCH:
        story.append(
            Paragraph(
                "The stored notice text failed its SHA-256 integrity check. "
                "Cited excerpts are withheld.",
                styles["BodyText"],
            )
        )
        return
    source = snapshot.notice_source
    if source is None:
        story.append(
            Paragraph(
                "No notice source text is stored for this notice version. "
                "Span IDs alone do not reproduce the source.",
                styles["BodyText"],
            )
        )
        return
    _field(story, styles, "Notice version", snapshot.notice_version)
    _field(story, styles, "Origin", source.origin)
    _field(story, styles, "Loaded into RecallDesk (UTC)", source.retrieved_at_utc)
    _field(story, styles, "SHA-256 of stored text", source.sha256)
    _field(story, styles, "Stored text length", f"{len(source.text):,} characters")
    story.append(Paragraph("<b>Cited lines, quoted verbatim:</b>", styles["BodyText"]))
    for span_id, line in source.cited_excerpts.items():
        page = source.span_pages.get(span_id)
        where = f"{span_id}, page {page}" if page else span_id
        story.append(
            Paragraph(
                f"[{_text(where)}] &ldquo;{_text(line)}&rdquo;", styles["BodyText"]
            )
        )


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

    styles = _styles()
    story = []

    story.append(Paragraph("RecallDesk", styles["Title"]))
    story.append(Paragraph("Synthetic Recall Evidence Report", styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))

    _field(story, styles, "Case ID", snapshot.case_id)
    _field(story, styles, "Evidence revision", snapshot.revision)
    _field(story, styles, "Notice version", snapshot.notice_version)
    _field(story, styles, "Stock version", snapshot.stock_version)
    _field(story, styles, "Revision saved at (UTC)", snapshot.created_at_utc)
    _field(
        story,
        styles,
        "Report generated at (UTC)",
        datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    _field(story, styles, "Notice source URL", snapshot.source_url, link=True)
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
    _field(
        story,
        styles,
        "Notice source text",
        {
            SOURCE_VERIFIED: "Stored and intact (see Appendix A)",
            SOURCE_HASH_MISMATCH: "Failed integrity check",
        }.get(snapshot.notice_source_status, "Not stored"),
    )

    statuses = Counter(
        _review_status(finding_map[key], current_decisions.get(key), snapshot)[0]
        for key in sorted(finding_map)
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Findings at a glance", styles["Heading2"]))
    _field(
        story,
        styles,
        "Simulated reviews",
        f"{statuses.get('Recorded', 0)} recorded, {statuses.get('Pending', 0)} "
        f"pending, {statuses.get('Blocked', 0)} blocked",
    )
    counts = Counter(entry.finding.state.value for entry in findings)
    _field(
        story,
        styles,
        "Saved finding totals",
        "; ".join(f"{state}: {count}" for state, count in sorted(counts.items())),
    )
    _summary_table(story, styles, snapshot, finding_map, current_decisions)

    _provenance(story, styles, snapshot)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Important limitations", styles["Heading2"]))
    story.append(Paragraph(SAFETY_STATEMENT, styles["BodyText"]))
    story.append(
        Paragraph(
            "All stock is synthetic. Reviewer roles and decisions "
            "are simulated, not authenticated professional approval. "
            "This report may include unreviewed or incomplete findings; "
            "export is not approval. The notice text is stored with its SHA-256 "
            "hash and cited lines are quoted in Appendix A, but the stored copy "
            "is what was loaded into RecallDesk, not proof that it matches the "
            "regulator's current page. Extraction provenance identifies the model "
            "call that drafted the notice, not that its output was correct. Consult "
            "the original source before relying on any finding. Local "
            "append-only database guards are not tamper-proof evidence.",
            styles["BodyText"],
        )
    )

    not_matched = []
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

        attention = []
        for row in snapshot.stock_rows:
            finding = finding_map.get((row.row_id, item_index))
            if finding is None:
                raise ValueError(f"Missing finding for {row.row_id}, item {item_index}")
            decision = current_decisions.get((row.row_id, item_index))
            block = _row_detail(styles, row, finding, decision)
            if finding.state is MatchState.NOT_MATCHED:
                not_matched.append((item_index, block))
            else:
                attention.append(block)

        heading = Paragraph(
            f"Rows needing attention ({len(attention)})"
            if attention
            else "No rows need attention for this product.",
            styles["Heading3"],
        )
        if attention:  # the heading stays on the page of the first row
            story.append(KeepTogether([heading, attention[0]]))
            story.extend(attention[1:])
        else:
            story.append(heading)

    _revision_history(story, styles, history)

    review_history = [Spacer(1, 5 * mm)]
    review_history.append(Paragraph("Simulated review history", styles["Heading2"]))
    if not decisions:
        story.extend(review_history)
        story.append(Paragraph("No review decisions recorded.", styles["BodyText"]))

    for position, decision in enumerate(decisions):
        status = (
            "CURRENT"
            if decision.revision == snapshot.revision
            else "HISTORICAL / STALE"
        )
        reviewed_item = history[decision.revision].notice_items[decision.item_index]

        decision_story = [] if position else list(review_history)
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

    _source_appendix(story, styles, snapshot)

    if not_matched:
        story.append(Spacer(1, 6 * mm))
        # The heading and statement stay on the page of the first row.
        story.append(
            KeepTogether(
                [
                    Paragraph(
                        "Appendix B: rows not matched to this notice",
                        styles["Heading2"],
                    ),
                    Paragraph(SAFETY_STATEMENT, styles["BodyText"]),
                    not_matched[0][1],
                ]
            )
        )
        story.extend(block for _, block in not_matched[1:])

    document.build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
    )

    return buffer.getvalue()
