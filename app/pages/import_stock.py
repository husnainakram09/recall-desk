"""Import stock page. Owned by Dev 1."""

import pandas as pd
import streamlit as st

from app import demo_fixtures, session
from ingestion.csv_loader import COLUMNS, parse_inventory_csv

_ERROR_BG = "background-color: #FDECEC"


def render() -> None:
    st.header("Import stock")
    st.caption("Synthetic stock data only. No real patient or pharmacy data.")

    upload = st.file_uploader("Stock CSV", type="csv")
    load_demo = st.button("Load synthetic demo stock")

    if load_demo:
        st.session_state[session.STOCK_CSV_TEXT] = demo_fixtures.stock_csv_text()
        st.session_state[session.STOCK_SOURCE] = demo_fixtures.STOCK_LABEL
        st.rerun()  # so the page-level synthetic banner shows immediately
    elif upload is not None and upload.file_id != st.session_state.get(
        session.STOCK_UPLOAD_ID
    ):
        try:
            text = upload.getvalue().decode("utf-8-sig")
        except UnicodeDecodeError:
            st.error(
                "This file is not UTF-8 text. Re-save it as CSV UTF-8 and try again."
            )
            return
        st.session_state[session.STOCK_UPLOAD_ID] = upload.file_id
        st.session_state[session.STOCK_CSV_TEXT] = text
        st.session_state[session.STOCK_SOURCE] = None
        st.rerun()

    text = st.session_state.get(session.STOCK_CSV_TEXT)
    if text is None:
        st.caption("Expected columns: " + ", ".join(COLUMNS))
        return
    source = st.session_state.get(session.STOCK_SOURCE)
    st.caption(f"Showing {source or 'the uploaded CSV'}.")

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

    overview_tab, parse_tab = st.tabs(
        [f"Stock overview ({good} rows)", f"Parse check ({bad} with errors)"]
    )
    with overview_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Row": row.row_id,
                        "Location": row.location,
                        "Product (as recorded)": row.product_raw,
                        "Strength": (
                            f"{row.strength.value:g} {row.strength.unit}"
                            if row.strength
                            else "-"
                        ),
                        "Batch": row.lot_raw if row.lot_raw is not None else "(blank)",
                        "Expiry": row.expiry_raw or "-",
                        "Pack": row.pack_size if row.pack_size is not None else "-",
                        "Qty": f"{row.quantity} {row.unit}",
                        "PL": next(
                            (c.value for c in row.codes if c.system == "UK_PL"), "-"
                        ),
                        "GTIN": next(
                            (c.value for c in row.codes if c.system == "GTIN"), "-"
                        ),
                    }
                    for row in result.rows
                ]
            ).astype(str),
            hide_index=True,
        )
        st.caption(
            "Identifiers are shown exactly as recorded. Blank batches stay blank."
        )
    with parse_tab:
        st.dataframe(
            preview.style.apply(shade, axis=1),
            hide_index=True,
            column_config={
                "line": st.column_config.NumberColumn("Line", width="small"),
                "status": st.column_config.TextColumn("Parse result", width="large"),
            },
        )
