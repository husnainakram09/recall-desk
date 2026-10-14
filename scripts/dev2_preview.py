"""Standalone Dev 2 review/export preview using saved or session evidence.

Run from the repository root:
    python -m streamlit run scripts/dev2_preview.py

Import Stock and Notice remain in the lead-owned application. This entry point
does not seed stock, notice drafts, reviewers, or review decisions.
"""

import streamlit as st

from app import session, theme
from app.pages import export, review

st.set_page_config(page_title="RecallDesk Dev 2 Preview", layout="wide")
theme.inject_css()

with st.sidebar:
    st.title("RecallDesk Dev 2 Preview")
    page = st.selectbox("Page", ("Review", "Export"))
    st.selectbox("Role", ("Technician", "Pharmacist"), key=session.ROLE)
    st.caption("Synthetic demonstration. Role selection is not authentication.")

if page == "Review":
    review.render()
else:
    export.render()
