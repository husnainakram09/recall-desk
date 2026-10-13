"""Streamlit entry point.

Run from the repo root:  python -m streamlit run app/main.py
"""

import streamlit as st

from app import session, theme
from app.pages import import_stock, notice

PAGES = ("Import Stock", "Notice", "Review", "Export")
ROLES = ("Technician", "Pharmacist")

st.set_page_config(page_title="RecallDesk", layout="wide")
theme.inject_css()

with st.sidebar:
    st.title("RecallDesk")
    page = st.selectbox("Page", PAGES)
    role = st.selectbox("Role", ROLES, key=session.ROLE)
    st.caption("All stock data is synthetic.")

if page == "Import Stock":
    import_stock.render()
elif page == "Notice":
    notice.render()
else:
    st.header(page)
    st.caption(f"Placeholder, owned by Dev 2. Viewing as {role}.")
