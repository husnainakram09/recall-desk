"""Dev 2: evidence-linked, provisional stock review.

This screen does not authenticate pharmacists or approve findings.
All results remain provisional until source and scope review.
"""

from dataclasses import replace

import streamlit as st

from app import session, theme
from app.pages.review_cases import (
    SOURCE_SNAPSHOT_KEY,
    render_case_controls,
)
from app.pages.review_decisions import render_review_decisions
from matching.engine import classify


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
        rows = st.session_state.get(session.INVENTORY) or []
        items = st.session_state.get(session.NOTICE_ITEMS) or []
    else:
        rows = saved_case.stock_rows
        items = saved_case.notice_items

    if not rows:
        st.info("Import synthetic stock on the Import Stock page.")
        return

    if not items:
        st.info("Prepare a notice draft on the Notice page.")
        return

    row_index = st.selectbox(
        "Stock record",
        range(len(rows)),
        format_func=lambda i: (
            f"{rows[i].row_id} — {rows[i].product_raw}"
        ),
    )

    item_index = st.selectbox(
        "Notice product",
        range(len(items)),
        format_func=lambda i: items[i].name,
    )

    row = rows[row_index]
    item = items[item_index]

    if saved_case is None:
        finding = classify(row, item)
    else:
        finding = next(
        (
            stored.finding
            for stored in saved_findings
            if stored.finding.row_id == row.row_id
            and stored.item_index == item_index
        ),
        None,
    )

    if finding is None:
        st.error("This saved case has no stored finding for the selected row.")
        return

    st.subheader("Provisional finding")
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

        if saved_case is None:
            notice = st.session_state.get(session.NOTICE_TEXT)
        else:
            source_snapshot = st.session_state.get(SOURCE_SNAPSHOT_KEY)
            notice = (
            source_snapshot[1]
        if source_snapshot and source_snapshot[0] == saved_case.case_id
        else None
        )

        if notice is not None:
            spans = {span.id: span for span in notice.spans}
            pages = notice.span_pages

            st.write("**Cited source excerpts:**")

            if not item.evidence_span_ids:
                st.warning("No source span is attached.")

            for span_id in item.evidence_span_ids:
                source = spans.get(span_id)

                theme.evidence_card(
                    label="Notice evidence",
                    value=span_id,
                    excerpt=source.text if source else None,
                    span_id=span_id,
                    page=pages.get(span_id),
                )
        else:
            st.warning(
                "The original notice text is not available "
                "in this session. Verify it before approval."
            )

    st.divider()
    st.subheader("Matching evidence")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.write("**Matched**")
        st.write(", ".join(finding.matched_fields) or "None")

    with c2:
        st.write("**Missing**")
        st.write(", ".join(finding.missing_fields) or "None")

    with c3:
        st.write("**Conflicting**")
        st.write(", ".join(finding.conflicting_fields) or "None")

        render_review_decisions(
        saved_case,
        row.row_id,
        item_index,
        finding,
    )

    st.divider()
    st.subheader("Preview a batch correction")

    st.caption(
        "For synthetic demonstration only. This preview does "
        "not save inventory changes or approve a finding."
    )

    with st.form("lot_preview"):
        new_lot = st.text_input(
            "Batch code from physical pack or receiving record",
            value=row.lot_raw or "",
        )

        confirmed = st.checkbox(
            "I checked the batch evidence (demo simulation)."
        )

        preview_clicked = st.form_submit_button(
            "Preview corrected finding"
        )

    if preview_clicked:
        if not confirmed:
            st.warning(
                "Confirm that evidence was checked before "
                "previewing a corrected record."
            )
        elif not new_lot.strip():
            st.warning("Enter the batch code to preview.")
        else:
            amended = replace(row, lot_raw=new_lot)
            preview = classify(amended, item)

            st.write("**Preview result:**")
            theme.state_badge(preview.state)
            st.write(preview.next_evidence)

            st.caption(
                "Not saved. A real correction must create a "
                "new stock revision and require fresh review."
            )

    st.caption(
        "No match in checked sources does not establish safety."
    )
