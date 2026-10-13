"""Notice page. Owned by Dev 1.

Load a notice, run extraction, and edit the draft beside the source text.
The model only proposes; the reviewer saves what goes forward.
"""

from collections.abc import Iterator
from html import escape

import pandas as pd
import requests
import streamlit as st

from app import session, theme
from config import ConfigError
from contracts import Code, LotScope, NoticeItem, Strength
from extraction.token_factory import CallMeta, ExtractionError, TokenFactoryAdapter
from extraction.validate import (
    ExtractedNotice,
    NoticeValidationError,
    appears_verbatim,
    extract_notice,
)
from ingestion.notice_reader import NoticeReadError, NoticeText, read_pasted, read_pdf

CODE_SYSTEMS = ["UK_PL", "GTIN"]
BLANK_ITEM = NoticeItem(
    name="",
    strength=None,
    form=None,
    holder=None,
    codes=(),
    lot_scope=LotScope.UNSPECIFIED,
    lots=(),
    pack_size=None,
    evidence_span_ids=(),
)


def render() -> None:
    st.header("Recall notice")
    notice = _load_notice()
    if notice is None:
        return

    _actions(notice)

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Source text")
        extraction = st.session_state.get(session.EXTRACTION)
        cited = (
            {sid for item in extraction.items for sid in item.evidence_span_ids}
            if extraction
            else set()
        )
        with st.container(height=640):
            theme.source_panel(notice.spans, cited, notice.span_pages)
    with right:
        _draft_panel(notice)


# -- notice input ------------------------------------------------------------


def _load_notice() -> NoticeText | None:
    tab_pdf, tab_paste = st.tabs(["Upload PDF", "Paste text"])
    with tab_pdf:
        upload = st.file_uploader("Notice PDF", type="pdf")
    with tab_paste:
        pasted = st.text_area("Notice text", height=180)

    previous: NoticeText | None = st.session_state.get(session.NOTICE_TEXT)
    try:
        if upload is not None:
            notice = read_pdf(upload.getvalue())
        elif pasted.strip():
            notice = read_pasted(pasted)
        else:
            # Widgets reset when the user visits another page; keep the notice.
            if previous is not None:
                st.caption("Showing the notice loaded earlier.")
            return previous
    except NoticeReadError as exc:
        st.error(str(exc))
        return None

    if previous is None or previous.text != notice.text:
        st.session_state[session.NOTICE_TEXT] = notice
        for key in (session.EXTRACTION, session.CALL_META, session.VALIDATION_ERRORS):
            st.session_state[key] = None
        _set_draft([], None)
    return notice


# -- extraction --------------------------------------------------------------


def _actions(notice: NoticeText) -> None:
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Run extraction", type="primary"):
        _run_extraction(notice)
    if c2.button("Start manual draft"):
        st.session_state[session.VALIDATION_ERRORS] = None
        _set_draft([BLANK_ITEM], None)

    meta = st.session_state.get(session.CALL_META)
    if meta is not None:
        _call_meta(meta, st.session_state.get(session.EXTRACTION))


def _run_extraction(notice: NoticeText) -> None:
    try:
        adapter = TokenFactoryAdapter()
    except ConfigError as exc:
        st.error(f"{exc} Start a manual draft meanwhile.")
        return

    st.session_state[session.VALIDATION_ERRORS] = None
    try:
        with st.spinner("Extracting with the AMD endpoint…"):
            result = extract_notice(adapter, notice.text)
    except NoticeValidationError as exc:
        st.session_state[session.CALL_META] = adapter.last_call_meta
        st.session_state[session.VALIDATION_ERRORS] = exc.errors
        _set_draft([BLANK_ITEM], None)
        return
    except (ExtractionError, requests.RequestException) as exc:
        st.session_state[session.CALL_META] = adapter.last_call_meta
        st.error(f"Extraction call failed: {exc}")
        return

    st.session_state[session.CALL_META] = adapter.last_call_meta
    _set_draft(list(result.items), result)


def _call_meta(meta: CallMeta, extraction: ExtractedNotice | None) -> None:
    parts = [
        f"Request ID {theme.identifier_html(meta.request_id)}",
        f"Latency <b>{meta.latency_ms:,.0f} ms</b>",
        f"Model {theme.identifier_html(meta.model)}",
        f"HTTP attempts {meta.attempts}",
    ]
    if extraction is not None:
        parts.append(f"Validation attempts {extraction.attempts}")
    if meta.usage and "total_tokens" in meta.usage:
        parts.append(f"Tokens {escape(str(meta.usage['total_tokens']))}")
    with st.container(border=True):
        st.markdown(
            "<b>AMD endpoint call</b> &nbsp; " + " &nbsp;·&nbsp; ".join(parts),
            unsafe_allow_html=True,
        )


# -- draft -------------------------------------------------------------------


def _set_draft(items: list[NoticeItem], extraction: ExtractedNotice | None) -> None:
    st.session_state[session.DRAFT] = items
    st.session_state[session.EXTRACTION] = extraction
    st.session_state[session.DRAFT_RUN] = st.session_state.get(session.DRAFT_RUN, 0) + 1
    _publish()


def _publish() -> None:
    draft = st.session_state.get(session.DRAFT) or []
    st.session_state[session.NOTICE_ITEMS] = [item for item in draft if item.name]


def _draft_panel(notice: NoticeText) -> None:
    st.subheader("Draft")
    errors = st.session_state.get(session.VALIDATION_ERRORS)
    if errors:
        st.warning(
            "The model's output failed validation twice and was discarded. "
            "Fill in the manual draft from the source text."
        )
        with st.expander("Validation errors"):
            st.code("\n".join(errors), language=None)

    draft: list[NoticeItem] | None = st.session_state.get(session.DRAFT)
    if not draft:
        st.info("Run extraction, or start a manual draft.")
        return
    if st.button("Add product"):
        draft.append(BLANK_ITEM)

    extraction: ExtractedNotice | None = st.session_state.get(session.EXTRACTION)
    spans = {s.id: s for s in notice.spans}
    labels = [_tab_label(i, item) for i, item in enumerate(draft)]
    for i, tab in enumerate(st.tabs(labels)):
        with tab:
            _item_form(i, draft[i])
            _unverified_warnings(draft[i], notice)
            if extraction is None or i >= len(extraction.items):
                continue
            original = extraction.items[i]
            if draft[i] != original:
                st.caption(
                    "Edited by reviewer. Evidence below is from the model's "
                    "original extraction."
                )
            with st.expander("Evidence", expanded=True):
                for label, value, is_id, sid in _evidence(
                    original, extraction.value_spans[i]
                ):
                    span = spans.get(sid)
                    theme.evidence_card(
                        label,
                        value,
                        span.text if span else None,
                        sid,
                        notice.span_pages.get(sid),
                        is_identifier=is_id,
                    )


def _tab_label(i: int, item: NoticeItem) -> str:
    name = item.name or "Untitled product"
    return f"{i + 1}. {name[:32]}{'…' if len(name) > 32 else ''}"


def _item_form(i: int, item: NoticeItem) -> None:
    key = f"draft{st.session_state.get(session.DRAFT_RUN, 0)}_{i}"
    scopes = [s.value for s in LotScope]
    with st.form(key):
        name = st.text_input("Product name", item.name, key=f"{key}_name")
        c1, c2 = st.columns(2)
        strength_value = c1.number_input(
            "Strength",
            value=item.strength.value if item.strength else None,
            min_value=0.0,
            key=f"{key}_strength",
        )
        unit = c2.text_input(
            "Strength unit",
            item.strength.unit if item.strength else "",
            key=f"{key}_unit",
        )
        form = c1.text_input("Form", item.form or "", key=f"{key}_form")
        holder = c2.text_input("Holder", item.holder or "", key=f"{key}_holder")
        pack_size = c1.number_input(
            "Pack size", value=item.pack_size, min_value=1, step=1, key=f"{key}_pack"
        )
        scope = c2.selectbox(
            "Lot scope",
            scopes,
            index=scopes.index(item.lot_scope.value),
            key=f"{key}_scope",
        )
        codes = st.data_editor(
            pd.DataFrame(
                {
                    "system": pd.Series([c.system for c in item.codes], dtype="string"),
                    "value": pd.Series([c.value for c in item.codes], dtype="string"),
                }
            ),
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "system": st.column_config.SelectboxColumn(
                    "Code system", options=CODE_SYSTEMS
                ),
                "value": st.column_config.TextColumn("Code, exactly as printed"),
            },
            key=f"{key}_codes",
        )
        lots = st.data_editor(
            pd.DataFrame({"lot": pd.Series(list(item.lots), dtype="string")}),
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "lot": st.column_config.TextColumn("Batch / lot, exactly as printed")
            },
            key=f"{key}_lots",
        )
        submitted = st.form_submit_button("Save product")

    if not submitted:
        return
    new_item, problems = _build_item(
        item, name, strength_value, unit, form, holder, pack_size, scope, codes, lots
    )
    if problems:
        for p in problems:
            st.error(p)
        return
    st.session_state[session.DRAFT][i] = new_item
    _publish()
    st.rerun()


def _build_item(
    original: NoticeItem,
    name: str,
    strength_value: float | None,
    unit: str,
    form: str,
    holder: str,
    pack_size: int | None,
    scope: str,
    codes_df: pd.DataFrame,
    lots_df: pd.DataFrame,
) -> tuple[NoticeItem | None, list[str]]:
    problems = []
    if not name.strip():
        problems.append("Product name is required.")

    strength = None
    if strength_value is not None and unit.strip():
        strength = Strength(float(strength_value), unit)
    elif strength_value is not None or unit.strip():
        problems.append("Give both a strength value and a unit, or neither.")

    codes = []
    for system, value in zip(codes_df["system"], codes_df["value"]):
        if not _filled(value):
            continue
        if system not in CODE_SYSTEMS:
            problems.append(f"Choose a code system for {value!r}.")
            continue
        codes.append(Code(system, value))

    lots = tuple(v for v in lots_df["lot"] if _filled(v))
    lot_scope = LotScope(scope)
    if lot_scope is LotScope.EXPLICIT_LIST and not lots:
        problems.append("explicit_list needs at least one lot.")
    if lot_scope is not LotScope.EXPLICIT_LIST and lots:
        problems.append(
            f"{lot_scope.value} must not list lots. Remove them or use explicit_list."
        )

    if problems:
        return None, problems
    return (
        NoticeItem(
            name=name,
            strength=strength,
            form=form if form.strip() else None,
            holder=holder if holder.strip() else None,
            codes=tuple(codes),
            lot_scope=lot_scope,
            lots=lots,
            pack_size=int(pack_size) if pack_size is not None else None,
            evidence_span_ids=original.evidence_span_ids,
        ),
        [],
    )


def _filled(value) -> bool:
    # Identifiers are kept exactly as typed; only fully blank cells are dropped.
    return isinstance(value, str) and bool(value.strip())


def _unverified_warnings(item: NoticeItem, notice: NoticeText) -> None:
    labelled = [(c.system, c.value) for c in item.codes] + [
        ("Lot", v) for v in item.lots
    ]
    for label, value in labelled:
        if not appears_verbatim(value, notice.text):
            st.warning(
                f"{label} {value!r} does not appear verbatim in the notice text."
            )


def _evidence(
    item: NoticeItem, value_spans: dict[str, str]
) -> Iterator[tuple[str, str | None, bool, str]]:
    """(label, value, is_identifier, span id) for every value the model cited."""
    for key, sid in value_spans.items():
        if key == "name":
            yield "Product name", item.name, False, sid
        elif key == "strength" and item.strength:
            yield (
                "Strength",
                f"{item.strength.value:g} {item.strength.unit}",
                False,
                sid,
            )
        elif key == "form":
            yield "Form", item.form, False, sid
        elif key == "holder":
            yield "Holder", item.holder, False, sid
        elif key == "pack_size":
            yield "Pack size", str(item.pack_size), False, sid
        elif key == "lot_scope":
            yield "Lot scope", item.lot_scope.value, False, sid
        elif key.startswith("codes["):
            code = item.codes[int(key[len("codes[") : -1])]
            yield code.system, code.value, True, sid
        elif key.startswith("lots["):
            yield "Lot", item.lots[int(key[len("lots[") : -1])], True, sid
