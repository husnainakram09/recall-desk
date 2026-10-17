"""Export page. Owned by Dev 2."""

import re
import sqlite3
from datetime import UTC, datetime

import streamlit as st
from reportlab.platypus.doctemplate import LayoutError

from app.pages.review_cases import ACTIVE_KEY, DB_PATH
from export.report import SAFETY_STATEMENT, build_case_report
from storage.db import connect, init_db
from storage.repository import get_revision, list_cases


def _report_filename(case_id: str, revision: int) -> str:
    label = re.sub(r"[^A-Za-z0-9_-]", "_", case_id)[:64] or "case"
    return f"recalldesk-{label}-r{revision}.pdf"


def render() -> None:
    st.header("Export saved case evidence")
    st.caption("Synthetic demonstration. Export does not approve any stock action.")
    st.warning(SAFETY_STATEMENT)
    st.caption(
        "The PDF uses saved evidence, the stored notice source snapshot and "
        "simulated decision history. Unsaved session inputs are not included."
    )

    conn = None
    try:
        conn = connect(DB_PATH)
        init_db(conn)
        cases = list_cases(conn)
        if not cases:
            st.info("Save a synthetic case on the Review page before exporting.")
            return

        options = [case.case_id for case in cases]
        active = st.session_state.get(ACTIVE_KEY)
        selected = st.selectbox(
            "Saved case to export",
            [None] + options,
            index=options.index(active) + 1 if active in options else 0,
            format_func=lambda value: value or "Select a saved case",
            key="dev2_export_case",
        )
        if selected is None:
            return

        snapshot = get_revision(conn, selected)
        st.info(f"Saved case {snapshot.case_id}, revision {snapshot.revision}")
        st.text(f"Recorded notice URL: {snapshot.source_url}")
        if not (snapshot.source_verified and snapshot.scope_reviewed):
            st.warning(
                "Source or scope review is incomplete. The PDF will retain "
                "this status and is not a clearance."
            )

        if st.button("Prepare saved-case PDF"):
            try:
                pdf = build_case_report(
                    conn, selected, expected_revision=snapshot.revision
                )
            except (ValueError, KeyError, TypeError, LayoutError) as exc:
                st.error(f"PDF could not be prepared: {exc}")
            else:
                st.download_button(
                    "Download evidence PDF",
                    data=pdf,
                    file_name=_report_filename(selected, snapshot.revision),
                    mime="application/pdf",
                    on_click="ignore",
                )
                prepared = datetime.now(UTC).strftime("%H:%M:%S UTC")
                st.caption(
                    f"Prepared at {prepared} from revision {snapshot.revision}. "
                    "If the case changes, prepare a new report: this one stays "
                    "tied to revision "
                    f"{snapshot.revision}."
                )
    except (sqlite3.Error, KeyError, ValueError, TypeError):
        st.error("The saved case could not be read. Check the local demo database.")
    finally:
        if conn is not None:
            conn.close()
