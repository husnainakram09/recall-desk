"""Saved synthetic case controls for the Streamlit review page.

Two separate contexts: building a new case from the current session, and
reviewing a saved case. Saved values are shown as saved, never mixed with
editable inputs for a different case.
"""

import sqlite3
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import session
from app.provenance import current_provenance
from storage.db import connect, init_db
from storage.repository import (
    SOURCE_HASH_MISMATCH,
    SOURCE_MISSING,
    SOURCE_VERIFIED,
    attach_notice_source,
    create_case,
    get_revision,
    list_cases,
    load_findings,
    make_notice_source,
    rereview_case,
    store_findings,
)

DB_PATH = Path(".recalldesk_demo.db")
ACTIVE_KEY = "dev2_active_case_id"

_MODES = {"new": "New case from this session", "open": "Open a saved case"}


def render_case_controls():
    """Return (saved revision, stored findings), or (None, None)."""
    pending = st.session_state.pop(session.REVIEW_MODE_NEXT, None)
    if pending:
        st.session_state[session.REVIEW_MODE] = pending
    if session.REVIEW_MODE not in st.session_state:
        st.session_state[session.REVIEW_MODE] = (
            "open" if st.session_state.get(ACTIVE_KEY) else "new"
        )

    mode = st.radio(
        "Work on",
        list(_MODES),
        format_func=_MODES.get,
        horizontal=True,
        key=session.REVIEW_MODE,
    )
    st.caption(
        "Refreshing the browser clears unsaved session work (stock, notice "
        "draft). Save a case to keep it, then reopen it under "
        "'Open a saved case' after a refresh."
    )

    conn = connect(DB_PATH)
    try:
        init_db(conn)
        if mode == "new":
            _render_new_case(conn)
            return None, None
        return _render_open_case(conn)
    finally:
        conn.close()


# -- new case -----------------------------------------------------------------


def _render_new_case(conn) -> None:
    rows = st.session_state.get(session.INVENTORY) or []
    items = st.session_state.get(session.NOTICE_ITEMS) or []
    notice = st.session_state.get(session.NOTICE_TEXT)
    ready = bool(rows and items and notice)

    st.markdown(
        f"This session: **{len(rows)}** stock rows · **{len(items)}** notice "
        f"product(s) · notice text **{'loaded' if notice else 'not loaded'}**. "
        "Findings below are previews until the case is saved."
    )
    if not ready:
        st.info(
            "To save a case: import stock, load a notice, and run extraction "
            "or save a manual draft on the Notice page."
        )

    meta = st.session_state.get(session.NOTICE_SOURCE)
    with st.form("review_new_case", enter_to_submit=False):
        source_url = st.text_input(
            "Notice source URL",
            value=meta["source_url"] if meta else "",
            placeholder="https://www.gov.uk/drug-device-alerts/...",
        )
        source_checked = st.checkbox(
            "I checked this draft against the notice source (simulation)."
        )
        scope_checked = st.checkbox(
            "I reviewed the affected product and lot scope (simulation)."
        )
        submitted = st.form_submit_button("Save as new case", disabled=not ready)

    if not submitted:
        return
    if not source_url.strip():
        st.error("Enter the notice source URL before saving.")
        return

    try:
        source = make_notice_source(
            notice.text,
            retrieved_at_utc=getattr(notice, "loaded_at_utc", None) or _utc_now(),
            origin=notice.source,
            cited_span_ids={sid for item in items for sid in item.evidence_span_ids},
            span_pages=notice.span_pages,
        )
        case_id = f"RD-{uuid4().hex[:12].upper()}"
        create_case(
            conn,
            case_id,
            source_url.strip(),
            items,
            rows,
            source_verified=source_checked,
            scope_reviewed=scope_checked,
            extraction_provenance=current_provenance(),
            notice_source=source,
        )
        store_findings(conn, case_id)
    except (ValueError, sqlite3.IntegrityError) as exc:
        st.error(f"Case could not be saved: {exc}")
        return

    st.session_state[ACTIVE_KEY] = case_id
    st.session_state[session.REVIEW_MODE_NEXT] = "open"
    st.toast(f"Saved case {case_id}")
    st.rerun()


# -- saved case ---------------------------------------------------------------


def _render_open_case(conn):
    cases = list_cases(conn)
    if not cases:
        st.info("No saved cases yet. Save one under 'New case from this session'.")
        return None, None

    by_id = {case.case_id: case for case in cases}
    options = list(by_id)
    active = st.session_state.get(ACTIVE_KEY)
    selected = st.selectbox(
        "Saved case",
        options,
        index=options.index(active) if active in options else 0,
        format_func=lambda cid: (
            f"{cid} · latest revision {by_id[cid].latest_revision} · "
            f"saved {by_id[cid].created_at_utc}"
        ),
    )
    st.session_state[ACTIVE_KEY] = selected

    snapshot = get_revision(conn, selected)
    _saved_case_panel(snapshot)
    snapshot = _render_source_recovery(conn, snapshot)
    snapshot = _render_rereview_controls(conn, snapshot)
    return snapshot, load_findings(conn, selected, snapshot.revision)


def _saved_case_panel(snapshot) -> None:
    source = snapshot.notice_source
    if snapshot.notice_source_status == SOURCE_VERIFIED:
        source_line = (
            f"stored and intact · SHA-256 <code>{source.sha256[:16]}…</code> · "
            f"loaded {escape(source.retrieved_at_utc)} · origin {escape(source.origin)}"
        )
    elif snapshot.notice_source_status == SOURCE_HASH_MISMATCH:
        source_line = "<b>failed its integrity check</b>"
    else:
        source_line = "<b>not stored</b>"

    with st.container(border=True):
        st.markdown(
            f"<b>Saved case {escape(snapshot.case_id)}</b> · revision "
            f"<b>{snapshot.revision}</b> (latest) · saved "
            f"{escape(snapshot.created_at_utc)}<br>"
            f"Notice source: {_link(snapshot.source_url)}<br>"
            f"Source check: <b>{_recorded(snapshot.source_verified)}</b> · "
            f"Lot scope review: <b>{_recorded(snapshot.scope_reviewed)}</b> "
            "(self-attested)<br>"
            f"Notice source text: {source_line}<br>"
            f"Last change: {escape(snapshot.change_note or 'not recorded')}",
            unsafe_allow_html=True,
        )
        st.caption(
            "These are the saved values of this case. Changes on the Import "
            "Stock and Notice pages do not alter it."
        )


def _render_source_recovery(conn, snapshot):
    """Attach source text to a case saved without it; decisions wait for it."""
    status = snapshot.notice_source_status
    if status == SOURCE_VERIFIED:
        return snapshot
    if status == SOURCE_HASH_MISMATCH:
        st.error(
            "The stored notice text no longer matches its SHA-256 hash. "
            "Review decisions are blocked. Save a new case from the original "
            "notice."
        )
        return snapshot

    st.warning(
        "Evidence unavailable: this case has no stored notice text, so its "
        "cited excerpts cannot be shown. Review decisions are blocked until "
        "the source is attached and re-reviewed."
    )
    notice = st.session_state.get(session.NOTICE_TEXT)
    if notice is None:
        st.caption("Load the original notice on the Notice page to attach it here.")
        return snapshot

    key = f"attach_{snapshot.case_id}_{snapshot.revision}"
    with st.form(key, enter_to_submit=False):
        st.caption(
            "Attach the notice loaded in this session. It must contain every "
            "cited line and every identifier in this case."
        )
        submitted = st.form_submit_button("Attach loaded notice as this case's source")
    if not submitted:
        return snapshot

    assert status == SOURCE_MISSING
    try:
        source = make_notice_source(
            notice.text,
            retrieved_at_utc=getattr(notice, "loaded_at_utc", None) or _utc_now(),
            origin=notice.source,
            cited_span_ids={
                sid for item in snapshot.notice_items for sid in item.evidence_span_ids
            },
            span_pages=notice.span_pages,
        )
        revision = attach_notice_source(
            conn,
            snapshot.case_id,
            expected_revision=snapshot.revision,
            notice_source=source,
        )
    except (ValueError, KeyError, sqlite3.Error) as exc:
        st.error(f"Source was not attached: {exc}")
        return snapshot
    st.success("Source attached. Re-review the source and scope below.")
    return get_revision(conn, snapshot.case_id, revision)


def _render_rereview_controls(conn, snapshot):
    """Collect new attestations bound to the displayed saved revision."""
    if snapshot.source_verified and snapshot.scope_reviewed:
        return snapshot
    if snapshot.notice_source_status != SOURCE_VERIFIED:
        return snapshot

    st.warning(
        "Source or scope review is incomplete for this revision. Recheck the "
        "notice source and this saved evidence before recording new "
        "self-attestations. These checks do not verify the source "
        "independently or authorize medicine handling."
    )
    key = f"dev2_rereview_{snapshot.case_id}_{snapshot.revision}"
    with st.form(key, enter_to_submit=False):
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


def _recorded(flag: bool) -> str:
    return "recorded" if flag else "not recorded"


def _link(url: str) -> str:
    safe = escape(url, quote=True)
    if url.startswith(("https://", "http://")) and " " not in url:
        return f'<a href="{safe}" target="_blank">{safe}</a>'
    return safe


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
