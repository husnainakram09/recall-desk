"""Extraction provenance: which AMD call drafted the notice, for the UI."""

from html import escape

import streamlit as st

from app import session
from app.theme import identifier_html
from storage.repository import ExtractionProvenance


def current_provenance() -> ExtractionProvenance | None:
    """Provenance for the notice draft in this session, or None if hand-drafted."""
    meta = st.session_state.get(session.CALL_META)
    extraction = st.session_state.get(session.EXTRACTION)
    if meta is None or extraction is None:
        return None
    items = st.session_state.get(session.NOTICE_ITEMS) or []
    return ExtractionProvenance(
        endpoint=meta.endpoint,
        model=meta.model,
        request_id=meta.request_id,
        latency_ms=meta.latency_ms,
        called_at_utc=meta.called_at_utc,
        edited_before_save=list(items) != list(extraction.items),
    )


def render_provenance(p: ExtractionProvenance | None, *, saved: bool) -> None:
    where = "saved with this case" if saved else "current session"
    with st.container(border=True):
        if p is None:
            st.markdown(
                f"<b>Extraction provenance</b> ({where}) &nbsp; No model call "
                "recorded: the notice was drafted manually.",
                unsafe_allow_html=True,
            )
            return
        parts = [
            f"Endpoint {identifier_html(p.endpoint)}",
            f"Model {identifier_html(p.model)}",
            f"Request ID {identifier_html(p.request_id)}",
            f"Latency <b>{p.latency_ms:,.0f} ms</b>",
            f"Called {escape(p.called_at_utc)}",
        ]
        if p.edited_before_save:
            parts.append("<b>Draft edited by reviewer before saving</b>")
        st.markdown(
            f"<b>Extraction provenance</b> ({where}) &nbsp; "
            + " &nbsp;·&nbsp; ".join(parts),
            unsafe_allow_html=True,
        )
