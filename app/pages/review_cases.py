
"""Saved synthetic case controls for the Streamlit review page."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import session
from app.provenance import current_provenance
from storage.db import connect, init_db
from storage.repository import (
    create_case,
    get_revision,
    list_cases,
    load_findings,
    rereview_case,
    store_findings,
)

DB_PATH = Path(".recalldesk_demo.db")
ACTIVE_KEY = "dev2_active_case_id"
SOURCE_SNAPSHOT_KEY = "dev2_notice_source_snapshot"


def _render_rereview_controls(conn, snapshot):
    """Collect new attestations bound to the displayed saved revision."""
    if snapshot.source_verified and snapshot.scope_reviewed:
        return snapshot

    st.warning(
        "Source or scope review remains incomplete. Review the recorded "
        "notice URL and this saved evidence before recording new "
        "self-attestations. These checks do not verify the source "
        "independently or authorize medicine handling."
    )
    key = f"dev2_rereview_{snapshot.case_id}_{snapshot.revision}"
    with st.form(key):
        source_checked = st.checkbox(
            "I rechecked the recorded notice source for this saved "
            "revision (simulation).",
            key=f"{key}_source",
        )
        scope_checked = st.checkbox(
            "I rechecked the affected product and lot scope for this "
            "saved revision (simulation).",
            key=f"{key}_scope",
        )
        submitted = st.form_submit_button(
            "Record source and scope review for saved revision"
        )

    if not submitted:
        return snapshot

    if not (source_checked and scope_checked):
        st.warning("Confirm both new checks before recording review.")
        return snapshot

    try:
        revision = rereview_case(
            conn,
            snapshot.case_id,
            expected_revision=snapshot.revision,
        )
    except (ValueError, KeyError, sqlite3.Error) as exc:
        st.error(f"Source and scope review was not recorded: {exc}")
        return snapshot

    st.success(
        f"Self-attestations saved as revision {revision}. Findings "
        "were recalculated; previous decisions remain historical."
    )
    return get_revision(conn, snapshot.case_id, revision)


def render_case_controls():
    """Return (saved revision, stored findings), or (None, None)."""
    with st.expander("Save or reopen a synthetic case", expanded=True):
        st.caption(
            "Local demonstration records only. Source and scope "
            "checkboxes are self-attested, not independently verified."
        )

        source_url = st.text_input(
            "Notice source URL",
            key="dev2_case_source_url",
            placeholder="https://example.org/synthetic-notice",
        )
        source_checked = st.checkbox(
            "I manually checked the notice source (simulation).",
            key="dev2_case_source_checked",
        )
        scope_checked = st.checkbox(
            "I reviewed the affected product and lot scope (simulation).",
            key="dev2_case_scope_checked",
        )

        save_clicked = st.button("Save current session as a new case")

        conn = connect(DB_PATH)
        try:
            init_db(conn)

            if save_clicked:
                rows = st.session_state.get(session.INVENTORY) or []
                items = st.session_state.get(session.NOTICE_ITEMS) or []

                if not rows or not items:
                    st.error("Import stock and prepare a notice first.")
                elif not source_url.strip():
                    st.error("Provide a notice source URL.")
                else:
                    case_id = f"RD-{uuid4().hex[:12].upper()}"

                    try:
                        create_case(
                            conn,
                            case_id,
                            source_url.strip(),
                            items,
                            rows,
                            source_verified=source_checked,
                            scope_reviewed=scope_checked,
                            extraction_provenance=current_provenance(),
                        )
                        store_findings(conn, case_id)
                    except (ValueError, sqlite3.IntegrityError) as exc:
                        st.error(f"Case could not be saved: {exc}")
                    else:
                        st.session_state[ACTIVE_KEY] = case_id
                        st.session_state[SOURCE_SNAPSHOT_KEY] = (
                            case_id,
                            st.session_state.get(session.NOTICE_TEXT),
                            1,
                        )
                        st.success(f"Saved case {case_id}")

            saved_cases = list_cases(conn)

            selected = st.selectbox(
                "Saved cases",
                options=[""] + [case.case_id for case in saved_cases],
                format_func=lambda value: value or "Select a saved case",
                key="dev2_saved_case_selector",
            )

            left, right = st.columns(2)

            if left.button("Open selected case", disabled=not selected):
                st.session_state[ACTIVE_KEY] = selected
                source_snapshot = st.session_state.get(SOURCE_SNAPSHOT_KEY)
                if source_snapshot and source_snapshot[0] != selected:
                    st.session_state.pop(SOURCE_SNAPSHOT_KEY, None)

            if right.button("Use current unsaved session"):
                st.session_state.pop(ACTIVE_KEY, None)

            active_id = st.session_state.get(ACTIVE_KEY)

            if active_id:
                snapshot = get_revision(conn, active_id)
                st.caption(f"Recorded notice URL: {snapshot.source_url}")
                snapshot = _render_rereview_controls(conn, snapshot)
                findings = load_findings(
                    conn, active_id, snapshot.revision
                )

                st.info(
                    f"Reviewing {snapshot.case_id}, "
                    f"revision {snapshot.revision}"
                )
                return snapshot, findings

        finally:
            conn.close()

    return None, None
