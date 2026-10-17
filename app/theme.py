"""Colours, match-state styling and CSS. Owned by Dev 1.

Every state badge, identifier and evidence card in the app comes from here so
they look identical on every page. All text is HTML-escaped before rendering:
notice and CSV content is untrusted.
"""

import re
from dataclasses import dataclass
from html import escape

import streamlit as st

from contracts import MatchState
from extraction.spans import Span


@dataclass(frozen=True)
class StateStyle:
    label: str
    icon: str
    colour: str  # text and border
    background: str


# NOT_MATCHED is neutral grey and never worded or coloured as "safe".
STATE_STYLES: dict[MatchState, StateStyle] = {
    MatchState.EXACT_CANDIDATE: StateStyle(
        "Exact candidate", "!", "#9B1C1C", "#FDECEC"
    ),
    MatchState.CONFLICTING_IDENTIFIERS: StateStyle(
        "Conflicting identifiers", "≠", "#9A4A06", "#FDF1E6"
    ),
    MatchState.NEEDS_EVIDENCE: StateStyle("Needs evidence", "?", "#7A5B00", "#FBF5DE"),
    MatchState.CHECK_INCOMPLETE: StateStyle(
        "Check incomplete", "…", "#4F4A85", "#EFEEF8"
    ),
    MatchState.NOT_MATCHED: StateStyle(
        "Not matched to this notice", "○", "#4A5561", "#EEF1F4"
    ),
}

_CSS = """
<style>
.rd-badge {
  display: inline-flex; align-items: center; gap: .4em;
  padding: .15em .65em; border: 1px solid; border-radius: 999px;
  font-size: .85rem; font-weight: 600; white-space: nowrap;
}
.rd-badge-icon { font-family: var(--rd-mono); }
:root {
  --rd-mono: ui-monospace, "Cascadia Mono", Consolas, "SFMono-Regular", Menlo,
             "Liberation Mono", monospace;
}
.rd-id {
  font-family: var(--rd-mono); font-feature-settings: "zero" 1;
  white-space: pre; background: #EEF2F5; border: 1px solid #D5DDE4;
  border-radius: 4px; padding: 0 .35em;
}
.rd-absent { color: #6B7785; font-style: italic; }
.rd-card {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  border: 1px solid #D5DDE4; border-radius: 6px; margin: .4rem 0;
  background: #FFFFFF;
}
.rd-card > div { padding: .55rem .75rem; min-width: 0; }
.rd-card-source { border-left: 1px solid #D5DDE4; background: #F7F9FA; }
.rd-card-label {
  font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
  color: #5B6773; margin-bottom: .2rem;
}
.rd-card-source .rd-quote { white-space: pre-wrap; overflow-wrap: anywhere; }
.rd-context { color: #6B7785; font-size: .82rem; border-bottom: 1px dashed #D5DDE4;
  margin-bottom: .2rem; padding-bottom: .1rem; }
.rd-card mark { background: #FFE9A8; padding: 0; }
.rd-source { font-size: .88rem; }
.rd-span { display: grid; grid-template-columns: 3.2em minmax(0, 1fr);
  padding: .1rem .25rem; border-radius: 3px; }
.rd-span-id { font-family: var(--rd-mono); color: #6B7785; font-size: .78rem;
  padding-top: .1rem; }
.rd-span-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.rd-span.rd-cited { background: #E7F0F4; }
.rd-synthetic {
  border: 2px dashed #7A5B00; background: #FBF5DE; color: #4A3700;
  border-radius: 6px; padding: .45rem .8rem; margin-bottom: .8rem;
  font-weight: 600; letter-spacing: .02em;
}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def synthetic_banner(source: str) -> None:
    """Shown on every page while demo fixture stock is loaded."""
    st.markdown(
        f'<div class="rd-synthetic">SYNTHETIC STOCK DATA · loaded from '
        f"{escape(source)} · not real pharmacy stock</div>",
        unsafe_allow_html=True,
    )


def badge_html(state: MatchState) -> str:
    s = STATE_STYLES[state]
    return (
        f'<span class="rd-badge" style="color:{s.colour};'
        f'background:{s.background};border-color:{s.colour}">'
        f'<span class="rd-badge-icon">{escape(s.icon)}</span>{escape(s.label)}</span>'
    )


def state_badge(state: MatchState) -> None:
    st.markdown(badge_html(state), unsafe_allow_html=True)


def identifier_html(value: str | None) -> str:
    """Monospace, slashed zero, whitespace shown as typed. None reads as absent."""
    if value is None:
        return '<span class="rd-absent">absent</span>'
    return f'<span class="rd-id">{escape(value)}</span>'


def identifier(value: str | None) -> None:
    st.markdown(identifier_html(value), unsafe_allow_html=True)


def evidence_card(
    label: str,
    value: str | None,
    excerpt: str | None,
    span_id: str | None = None,
    page: int | None = None,
    is_identifier: bool = False,
    context: str | None = None,
) -> None:
    """Extracted value on the left, verbatim source excerpt on the right.

    context is the source line before the cited one (often the table's
    column headings), shown muted so the cited value can be read in place.
    """
    if value is None:
        shown = '<span class="rd-absent">not stated</span>'
    elif is_identifier:
        shown = identifier_html(value)
    else:
        shown = escape(value)

    where = " · ".join(
        part for part in (span_id, f"page {page}" if page else None) if part
    )
    source_label = f"Source {escape(where)}" if where else "Source"
    quote = (
        _highlight(excerpt, value)
        if excerpt is not None
        else '<span class="rd-absent">no source span</span>'
    )
    if context is not None and excerpt is not None:
        quote = f'<div class="rd-context">{escape(context)}</div>{quote}'
    st.markdown(
        f'<div class="rd-card">'
        f'<div><div class="rd-card-label">{escape(label)}</div>{shown}</div>'
        f'<div class="rd-card-source"><div class="rd-card-label">{source_label}</div>'
        f'<div class="rd-quote">{quote}</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def source_panel(
    spans: tuple[Span, ...], cited: set[str] = frozenset(), pages: dict | None = None
) -> None:
    """The notice as numbered spans, with cited spans shaded."""
    pages = pages or {}
    rows = []
    for span in spans:
        cls = "rd-span rd-cited" if span.id in cited else "rd-span"
        title = f' title="page {pages[span.id]}"' if span.id in pages else ""
        rows.append(
            f'<div class="{cls}"{title}><span class="rd-span-id">{span.id}</span>'
            f'<span class="rd-span-text">{escape(span.text)}</span></div>'
        )
    st.markdown(f'<div class="rd-source">{"".join(rows)}</div>', unsafe_allow_html=True)


def _highlight(excerpt: str, value: str | None) -> str:
    """Mark the first whole-value occurrence of value in the excerpt.

    "28" marks a standalone 28, never the 28 inside "01/2028".
    """
    match = (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", excerpt)
        if value
        else None
    )
    if match is None:
        return escape(excerpt)
    at, end = match.span()
    return (
        f"{escape(excerpt[:at])}<mark>{escape(excerpt[at:end])}</mark>"
        f"{escape(excerpt[end:])}"
    )
