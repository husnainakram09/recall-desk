"""Notice PDF or pasted text -> text plus span map.

Spans come from extraction.spans.split_spans, the same function the validator
uses, so span ids shown in the UI always match the ones the model cites.
Extracted text is returned as pypdf produced it; nothing is cleaned up.
"""

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from extraction.spans import Span, split_spans


class NoticeReadError(ValueError):
    pass


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class NoticeText:
    text: str
    spans: tuple[Span, ...]
    source: str  # "pdf" | "paste" | "fixture"
    span_pages: dict[str, int] = field(default_factory=dict)  # PDF only, 1-based
    loaded_at_utc: str = field(default_factory=_now_utc)  # when read into the app


def read_pasted(text: str) -> NoticeText:
    if not text.strip():
        raise NoticeReadError("Pasted notice is empty.")
    return NoticeText(text=text, spans=split_spans(text), source="paste")


def read_pdf(source: str | Path | bytes | BinaryIO) -> NoticeText:
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        pages = [page.extract_text() or "" for page in PdfReader(source).pages]
    except (PdfReadError, OSError, ValueError) as exc:
        raise NoticeReadError(f"Could not read PDF: {exc}") from exc

    text = "\n".join(pages)
    if not text.strip():
        raise NoticeReadError(
            "PDF has no text layer (it may be scanned). Paste the notice text instead."
        )

    spans = split_spans(text)
    span_pages = {}
    ids = iter(s.id for s in spans)
    for page_no, page_text in enumerate(pages, 1):
        for _ in split_spans(page_text):
            span_pages[next(ids)] = page_no
    return NoticeText(text=text, spans=spans, source="pdf", span_pages=span_pages)
