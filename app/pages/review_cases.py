
"""Saved synthetic case controls for the Streamlit review page."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import session
from storage.db import connect, init_db
from storage.repository import (
    create_case,
    get_revision,
    list_cases,
    load_findings,
    store_findings,
)

DB_PATH = Path(".recalldesk_demo.db")
ACTIVE_KEY = "dev2_active_case_id"
SOURCE_SNAPSHOT_KEY = "dev2_notice_source_snapshot"


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
                        )
                        store_findings(conn, case_id)
                    except (ValueError, sqlite3.IntegrityError) as exc:
                        st.error(f"Case could not be saved: {exc}")
                    else:
                        st.session_state[ACTIVE_KEY] = case_id
                        st.session_state[SOURCE_SNAPSHOT_KEY] = (
                            case_id,
                            st.session_state.get(session.NOTICE_TEXT),
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
                findings = load_findings(conn, active_id)

                st.info(
                    f"Reviewing {snapshot.case_id}, "
                    f"revision {snapshot.revision}"
                )
                st.caption(f"Recorded notice URL: {snapshot.source_url}")

                if not (snapshot.source_verified and snapshot.scope_reviewed):
                    st.warning(
                        "Source or scope review remains incomplete. "
                        "Stored findings are not cleared for review."
                    )

                return snapshot, findings

        finally:
            conn.close()

    return None, None
