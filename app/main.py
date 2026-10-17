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
from app.pages.review_cases import ACTIVE_KEY

PAGES = ("Import Stock", "Notice", "Review", "Export")
ROLES = ("Technician", "Pharmacist")

st.set_page_config(page_title="RecallDesk", layout="wide")
theme.inject_css()

STEPS = (
    ("Import stock", "Import Stock", session.INVENTORY),
    ("Load the recall notice", "Notice", session.NOTICE_TEXT),
    ("Run extraction or save a manual draft", "Notice", session.NOTICE_ITEMS),
    ("Save the case", "Review", ACTIVE_KEY),
    ("Review flagged rows and record decisions", "Review", None),
    ("Export the evidence PDF", "Export", None),
)


def _step_guide() -> None:
    lines, next_marked = [], False
    for number, (label, page_name, key) in enumerate(STEPS, 1):
        done = key is not None and bool(st.session_state.get(key))
        if done:
            mark = "✓"
        elif not next_marked:
            mark, next_marked = "→", True
        else:
            mark = "○"
        text = f"{mark} {number}. {label} *({page_name})*"
        lines.append(f"**{text}**" if mark == "→" else text)
    st.markdown("  \n".join(lines))


with st.sidebar:
    st.title("RecallDesk")
    page = st.selectbox("Page", PAGES)
    role = st.selectbox("Role", ROLES, key=session.ROLE)
    st.caption("All stock data is synthetic.")
    st.divider()
    st.caption("Steps")
    _step_guide()
    st.caption("Refreshing the browser clears unsaved work. Save a case to keep it.")

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
