
"""Simulated review actions and revision-bound decision history."""

import sqlite3

import streamlit as st

from app import session
from app.pages.review_cases import DB_PATH
from contracts import MatchState
from storage.db import connect
from storage.repository import (
    load_review_decisions,
    record_review_decision,
)
from storage.review_policy import ReviewAction

_ACTIONS = {
    MatchState.EXACT_CANDIDATE: (
        ReviewAction.ACKNOWLEDGE_CANDIDATE,
        "Acknowledge recall candidate",
    ),
    MatchState.NEEDS_EVIDENCE: (
        ReviewAction.REQUEST_EVIDENCE,
        "Request additional evidence",
    ),
    MatchState.CONFLICTING_IDENTIFIERS: (
        ReviewAction.ESCALATE_CONFLICT,
        "Escalate conflicting identifiers",
    ),
    MatchState.NOT_MATCHED: (
        ReviewAction.RECORD_NONMATCH,
        "Record non-match for this notice",
    ),
}


def render_review_decisions(saved_case, row_id, item_index, finding):
    """Render review controls for a saved evidence revision."""
    st.divider()
    st.subheader("Simulated review decision")
    st.caption(
        "Educational demonstration only. Role selection is not "
        "authentication and no medicine-handling action is authorized."
    )

    if saved_case is None:
        st.info("Save or open a synthetic case before recording a decision.")
        return

    role = st.session_state.get(session.ROLE)

    if role is None:
        role = st.selectbox(
            "Simulated role (standalone preview)",
            ("Technician", "Pharmacist"),
            key="dev2_preview_reviewer_role",
        )

    conn = connect(DB_PATH)

    try:
        history = load_review_decisions(conn, saved_case.case_id)

        current = next(
            (
                decision
                for decision in history
                if decision.is_current
                and decision.row_id == row_id
                and decision.item_index == item_index
            ),
            None,
        )

        choice = _ACTIONS.get(finding.state)

        if current is not None:
            st.success(
                "A simulated decision has already been recorded "
                "for this finding and revision."
            )
        elif choice is None:
            st.warning(
                "This finding is incomplete. Review decisions "
                "are blocked until required evidence is available."
            )
        elif not (
            saved_case.source_verified and saved_case.scope_reviewed
        ):
            st.warning("Source and scope review are incomplete.")
        else:
            action, label = choice

            with st.form(
                f"decision_{saved_case.case_id}_"
                f"{saved_case.revision}_{row_id}_{item_index}"
            ):
                reviewer = st.text_input("Demonstration reviewer label")
                note = st.text_area(
                    "Review note",
                    placeholder="Explain the simulated review action.",
                )
                submitted = st.form_submit_button(
                    label,
                    disabled=role != "Pharmacist",
                )

            if role != "Pharmacist":
                st.info(
                    "Select the simulated Pharmacist role to "
                    "record a review action."
                )

            if submitted:
                try:
                    record_review_decision(
                        conn,
                        saved_case.case_id,
                        saved_case.revision,
                        row_id,
                        item_index,
                        action,
                        reviewer,
                        role,
                        note=note,
                    )
                except (
                    ValueError,
                    KeyError,
                    PermissionError,
                    sqlite3.IntegrityError,
                ) as exc:
                    st.error(f"Decision was not recorded: {exc}")
                else:
                    st.success("Simulated decision recorded in SQLite.")
                    history = load_review_decisions(
                        conn, saved_case.case_id
                    )

        with st.expander("Review decision history", expanded=True):
            relevant = [
                decision
                for decision in history
                if decision.row_id == row_id
                and decision.item_index == item_index
            ]

            if not relevant:
                st.caption("No decisions recorded for this stock row.")
            else:
                for decision in reversed(relevant):
                    status = (
                        "CURRENT"
                        if decision.is_current
                        else "HISTORICAL / STALE"
                    )
                    st.write(
                        f"Revision {decision.revision} — {status}"
                    )
                    st.text(
                        f"Action: {decision.action.value}\n"
                        f"Reviewer: {decision.reviewer_label}\n"
                        f"Recorded: {decision.decided_at_utc}\n"
                        f"Note: {decision.note or '(none)'}"
                    )

    finally:
        conn.close()
