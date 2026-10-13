"""Streamlit entry point.

Run from the repo root:  python -m streamlit run app/main.py
"""

import streamlit as st

PAGES = ("Import Stock", "Notice", "Review", "Export")
ROLES = ("Technician", "Pharmacist")

st.set_page_config(page_title="RecallDesk", layout="wide")

with st.sidebar:
    st.title("RecallDesk")
    page = st.selectbox("Page", PAGES)
    role = st.selectbox("Role", ROLES)
    st.caption("All stock data is synthetic.")

st.header(page)
st.caption(f"Placeholder. Viewing as {role}.")
