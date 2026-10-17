"""Dev 2: evidence-linked, provisional stock review.

This screen does not authenticate pharmacists or approve findings.
All results remain provisional until source and scope review.
"""

import sqlite3
from dataclasses import replace

import pandas as pd
import streamlit as st

from app import session, theme
from app.pages.review_cases import DB_PATH, render_case_controls
from app.pages.review_decisions import ACTION_LABELS, render_review_decisions
from app.provenance import current_provenance, render_provenance
from contracts import MatchState
from extraction.spans import split_spans
from matching.engine import classify
from storage.db import connect
from storage.repository import (
    SOURCE_VERIFIED,
    correct_stock_lot,
    load_review_decisions,
)


def render() -> None:
    st.header("Stock recall review")
    st.caption("Historical educational replay. Synthetic inventory only.")

    st.warning(
        "Provisional findings. This screen does not verify the "
        "official notice, approve stock actions, or establish "
        "medicine safety."
    )

    saved_case, saved_findings = render_case_controls()

    if saved_case is None:
        render_provenance(current_provenance(), saved=False)
        rows = st.session_state.get(session.INVENTORY) or []
        items = st.session_state.get(session.NOTICE_ITEMS) or []
    else:
        render_provenance(saved_case.extraction_provenance, saved=True)
        rows = saved_case.stock_rows
        items = saved_case.notice_items

    if not rows:
        st.info("Import synthetic stock on the Import Stock page.")
        return

    if not items:
        st.info("Prepare a notice draft on the Notice page.")
        return

    item_index = st.selectbox(
        "Notice product",
        range(len(items)),
        format_func=lambda i: items[i].name,
    )
    item = items[item_index]

    if saved_case is None:
        findings = {row.row_id: classify(row, item) for row in rows}
        decisions = {}
    else:
        findings = {
            stored.finding.row_id: stored.finding
            for stored in saved_findings
            if stored.item_index == item_index
        }
        decisions = _current_decisions(saved_case.case_id, item_index)

    _findings_table(rows, findings, decisions, saved_case)

    row_index = st.selectbox(
        "Stock record to inspect",
        range(len(rows)),
        format_func=lambda i: f"{rows[i].row_id} — {rows[i].product_raw}",
    )
    row = rows[row_index]
    finding = findings.get(row.row_id)

    if finding is None:
        st.error("This saved case has no stored finding for the selected row.")
        return

    st.subheader(f"Row {row.row_id}: provisional finding")
    theme.state_badge(finding.state)
    st.info(finding.next_evidence or "Manual review required.")

    left, right = st.columns(2, gap="large")

    with left:
        st.subheader("Pharmacy inventory")

        with st.container(border=True):
            st.write("**Row ID:**", row.row_id)
            st.write("**Location:**", row.location)
            st.write("**Product:**", row.product_raw)

            strength = (
                f"{row.strength.value:g} {row.strength.unit}"
                if row.strength
                else "Not recorded"
            )
            st.write("**Strength:**", strength)
            st.write("**Form:**", row.form or "Not recorded")
            st.write("**Quantity:**", f"{row.quantity} {row.unit}")

            st.write("**Batch / lot:**")
            theme.identifier(row.lot_raw)

            st.write("**Stock identifiers:**")
            for code in row.codes:
                st.write(code.system)
                theme.identifier(code.value)

    with right:
        st.subheader("Notice evidence")

        with st.container(border=True):
            st.write("**Product:**", item.name)

            strength = (
                f"{item.strength.value:g} {item.strength.unit}"
                if item.strength
                else "Not stated"
            )
            st.write("**Strength:**", strength)
            st.write("**Lot scope:**", item.lot_scope.value)

            st.write("**Affected lots:**")
            for lot in item.lots:
                theme.identifier(lot)

            st.write("**Notice identifiers:**")
            for code in item.codes:
                st.write(code.system)
                theme.identifier(code.value)

        _cited_excerpts(item, saved_case)

    st.divider()
    st.subheader("Matching evidence")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.write("**Matched**")
        st.write(", ".join(finding.matched_fields) or "None")

    with c2:
        st.write("**Missing**")
        st.write(", ".join(finding.missing_fields) or "None")

    with c3:
        st.write("**Conflicting**")
        st.write(", ".join(finding.conflicting_fields) or "None")

    with c4:
        st.write("**Wording differs (informational)**")
        st.write(", ".join(finding.descriptive_differences) or "None")

    render_review_decisions(
        saved_case,
        row.row_id,
        item_index,
        finding,
    )

    _correction_form(saved_case, row, item, item_index)

    st.caption("No match in checked sources does not establish safety.")


def _current_decisions(case_id, item_index):
    conn = connect(DB_PATH)
    try:
        return {
            decision.row_id: decision
            for decision in load_review_decisions(conn, case_id)
            if decision.is_current and decision.item_index == item_index
        }
    finally:
        conn.close()


def _findings_table(rows, findings, decisions, saved_case) -> None:
    """Every stock row against the selected notice product, at a glance."""
    st.subheader("All stock rows")
    counts = {}
    for finding in findings.values():
        counts[finding.state] = counts.get(finding.state, 0) + 1
    st.markdown(
        " ".join(
            f"{theme.badge_html(state)} <b>{counts[state]}</b>"
            for state in theme.STATE_STYLES
            if state in counts
        ),
        unsafe_allow_html=True,
    )

    records = []
    for row in rows:
        finding = findings.get(row.row_id)
        if finding is None:
            continue
        style = theme.STATE_STYLES[finding.state]
        records.append(
            {
                "Row": row.row_id,
                "Product (as recorded)": row.product_raw,
                "Batch": row.lot_raw if row.lot_raw is not None else "(not recorded)",
                "Finding": f"{style.icon} {style.label}",
                "Gaps / conflicts": ", ".join(
                    finding.missing_fields + finding.conflicting_fields
                )
                or "-",
                "Review": _decision_status(
                    finding, decisions.get(row.row_id), saved_case
                ),
                "Next evidence": finding.next_evidence or "",
                "_state": finding.state.value,
            }
        )
    table = pd.DataFrame(records)

    def shade(record):
        style = theme.STATE_STYLES[MatchState(record["_state"])]
        return [f"background-color: {style.background}"] * len(record)

    st.dataframe(
        table.style.apply(shade, axis=1),
        hide_index=True,
        column_order=[c for c in table.columns if c != "_state"],
        column_config={
            "Row": st.column_config.TextColumn(width="small"),
            "Next evidence": st.column_config.TextColumn(width="large"),
        },
    )


def _decision_status(finding, decision, saved_case) -> str:
    if saved_case is None:
        return "Save the case to review"
    if decision is not None:
        return f"Recorded: {ACTION_LABELS[decision.action]}"
    if finding.state is MatchState.CHECK_INCOMPLETE:
        return "Blocked: complete source and scope review"
    if saved_case.notice_source_status != SOURCE_VERIFIED:
        return "Blocked: source text unavailable"
    return "Pending"


def _cited_excerpts(item, saved_case) -> None:
    """The exact notice lines this product cites, each with the line above it."""
    if saved_case is None:
        notice = st.session_state.get(session.NOTICE_TEXT)
        text, pages = (notice.text, notice.span_pages) if notice else (None, {})
    elif saved_case.notice_source_status == SOURCE_VERIFIED:
        text = saved_case.notice_source.text
        pages = saved_case.notice_source.span_pages
    else:
        text, pages = None, {}

    if text is None:
        st.warning(
            "The original notice text is not available for this case, so its "
            "cited excerpts cannot be shown. Decisions stay blocked until the "
            "source is attached."
        )
        return

    spans = split_spans(text)
    cited = set(item.evidence_span_ids)
    if not cited:
        st.warning("No source span is attached to this notice product.")
        return

    shown = []
    for index, span in enumerate(spans):
        if span.id in cited:
            if index and spans[index - 1] not in shown:
                shown.append(spans[index - 1])
            shown.append(span)
    st.write("**Cited source lines** (shaded; the line above each gives context):")
    theme.source_panel(tuple(shown), cited, pages)


def _correction_form(saved_case, row, item, item_index) -> None:
    st.divider()
    st.subheader(f"Correct the batch for row {row.row_id}")

    st.caption(
        "Preview a synthetic batch correction, or save it as "
        "a new evidence revision. Saving resets source and "
        "scope review flags and requires fresh review."
    )

    # Keyed by case, revision, row and product: a confirmation given for
    # one pack never carries over to another row or a later revision.
    key = (
        f"lot_{saved_case.case_id if saved_case else 'session'}_"
        f"{saved_case.revision if saved_case else 0}_{row.row_id}_{item_index}"
    )
    with st.form(key, enter_to_submit=False):
        new_lot = st.text_input(
            f"Batch code for row {row.row_id}, read from the physical pack "
            "or receiving record",
            value=row.lot_raw or "",
            key=f"{key}_lot",
        )
        reason = st.text_input(
            "Where was it read? (for example: blister foil, receiving record)",
            key=f"{key}_reason",
        )
        confirmed = st.checkbox(
            f"I checked the batch evidence for row {row.row_id} (demo simulation).",
            value=False,
            key=f"{key}_confirmed",
        )

        preview_clicked = st.form_submit_button("Preview corrected finding")

        save_clicked = st.form_submit_button(
            "Save correction as new revision",
            disabled=saved_case is None,
        )

    if saved_case is None:
        st.caption("Save or open a case above to enable persistent corrections.")

    if not (preview_clicked or save_clicked):
        return

    if not confirmed:
        st.warning(f"Confirm the batch evidence for row {row.row_id} first.")
        return

    if not new_lot.strip():
        st.warning("Enter a non-empty batch code.")
        return

    if save_clicked:
        if not reason.strip():
            st.warning("Say where the batch was read before saving.")
            return
        conn = connect(DB_PATH)
        try:
            revision = correct_stock_lot(
                conn,
                saved_case.case_id,
                expected_revision=saved_case.revision,
                row_id=row.row_id,
                lot_raw=new_lot,
                reason=reason,
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            sqlite3.IntegrityError,
        ) as exc:
            st.error(f"Correction was not saved: {exc}")
        else:
            st.toast(
                f"Correction saved as revision {revision}. Previous review "
                "decisions are now historical."
            )
            st.rerun()
        finally:
            conn.close()
        return

    preview = classify(replace(row, lot_raw=new_lot), item)
    st.write("**Provisional preview result:**")
    theme.state_badge(preview.state)
    st.write(preview.next_evidence or "Manual review still required.")
    st.caption("Preview only. No inventory revision was saved.")
