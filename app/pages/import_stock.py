"""Import stock page. Owned by Dev 1."""

import pandas as pd
import streamlit as st

from app import session
from ingestion.csv_loader import COLUMNS, parse_inventory_csv

_ERROR_BG = "background-color: #FDECEC"


def render() -> None:
    st.header("Import stock")
    st.caption("Synthetic stock data only. No real patient or pharmacy data.")

    upload = st.file_uploader("Stock CSV", type="csv")
    if upload is None:
        loaded = st.session_state.get(session.INVENTORY)
        if loaded:
            st.info(
                f"{len(loaded)} stock rows loaded. Upload a new file to replace them."
            )
        st.caption("Expected columns: " + ", ".join(COLUMNS))
        return

    try:
        text = upload.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        st.error("This file is not UTF-8 text. Re-save it as CSV UTF-8 and try again.")
        return

    result = parse_inventory_csv(text)
    for err in (e for e in result.errors if e.line == 1):
        st.error(f"Header: {err.message}")
    if not result.raw_records:
        return

    errors_by_line: dict[int, list[str]] = {}
    for err in result.errors:
        if err.line > 1:
            errors_by_line.setdefault(err.line, []).append(err.message)

    st.session_state[session.INVENTORY] = result.rows

    good, bad = len(result.rows), len(errors_by_line)
    c1, c2 = st.columns(2)
    c1.metric("Rows loaded", good)
    c2.metric("Rows with errors", bad)
    if bad:
        st.warning(
            f"{bad} row(s) could not be read and are NOT included in the check. "
            "Fix them in the CSV and upload again."
        )

    preview = pd.DataFrame(
        [
            {
                "line": line,
                "status": "; ".join(errors_by_line[line])
                if line in errors_by_line
                else "OK",
                **{c: cells.get(c) or "" for c in COLUMNS},
            }
            for line, cells in result.raw_records
        ]
    ).astype({c: "string" for c in COLUMNS})

    def shade(row: pd.Series) -> list[str]:
        return [_ERROR_BG if row["status"] != "OK" else ""] * len(row)

    st.dataframe(
        preview.style.apply(shade, axis=1),
        hide_index=True,
        column_config={
            "line": st.column_config.NumberColumn("Line", width="small"),
            "status": st.column_config.TextColumn("Parse result", width="large"),
        },
    )
