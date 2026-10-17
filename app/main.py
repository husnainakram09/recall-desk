"""Streamlit entry point.

Run from the repo root:  python -m streamlit run app/main.py
"""

import sys
from pathlib import Path

# `streamlit run app/main.py` (as Streamlit Community Cloud runs it) puts only
# app/ on the import path. Add the repo root so top-level packages resolve.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

from app import session, theme
from app.pages import export, import_stock, notice, review

PAGES = ("Import Stock", "Notice", "Review", "Export")
ROLES = ("Technician", "Pharmacist")

st.set_page_config(page_title="RecallDesk", layout="wide")
theme.inject_css()

with st.sidebar:
    st.title("RecallDesk")
    page = st.selectbox("Page", PAGES)
    role = st.selectbox("Role", ROLES, key=session.ROLE)
    st.caption("All stock data is synthetic.")

if st.session_state.get(session.STOCK_SOURCE):
    theme.synthetic_banner(st.session_state[session.STOCK_SOURCE])

if page == "Import Stock":
    import_stock.render()
elif page == "Notice":
    notice.render()
elif page == "Review":
    review.render()
elif page == "Export":
    export.render()
