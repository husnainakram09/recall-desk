"""Turn the model's JSON into NoticeItems, checking every value against the source.

Parsing is not trust. Every identifier must appear verbatim in the notice text
and in the span the model cited for it, and every batch must sit under the
product that claims it.
"""

import re
from dataclasses import dataclass

from contracts import Code, LotScope, NoticeItem, Strength
from extraction.adapter import ModelAdapter
from extraction.prompts import build_retry_message, build_user_message
from extraction.spans import Span, split_spans

ITEM_KEYS = frozenset(
    {"name", "strength", "form", "holder", "codes", "lot_scope", "lots", "pack_size"}
)
VALUE_KEYS = frozenset({"value", "span"})
CODE_SYSTEMS = frozenset({"UK_PL", "GTIN"})


class NoticeValidationError(Exception):
    """Raised after the retry also fails. The UI falls back to a manual draft."""

    def __init__(self, errors: list[str], raw: dict):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.raw = raw


@dataclass(frozen=True)
class ExtractedNotice:
    items: tuple[NoticeItem, ...]
    value_spans: tuple[dict[str, str], ...]  # per item: "lots[0]" -> "S6"
    spans: tuple[Span, ...]
    attempts: int


def extract_notice(adapter: ModelAdapter, text: str) -> ExtractedNotice:
    spans = split_spans(text)
    raw = adapter.extract(build_user_message(spans))
    items, value_spans, errors = parse_notice(raw, spans)
    attempts = 1
    if errors:
        raw = adapter.extract(build_retry_message(spans, raw, errors))
        items, value_spans, errors = parse_notice(raw, spans)
        attempts = 2
    if errors:
        raise NoticeValidationError(errors, raw)
    return ExtractedNotice(items, value_spans, spans, attempts)


def parse_notice(
    raw: dict, spans: tuple[Span, ...]
) -> tuple[tuple[NoticeItem, ...], tuple[dict[str, str], ...], list[str]]:
    """Return (items, value_spans, errors). Items are only usable if errors is empty."""
    parser = _Parser(spans)
    items, value_spans = parser.parse(raw)
    return items, value_spans, parser.errors


class _Parser:
    def __init__(self, spans: tuple[Span, ...]):
        self.spans = {s.id: s for s in spans}
        self.order = {s.id: i for i, s in enumerate(spans)}
        self.source = "\n".join(s.text for s in spans)
        self.errors: list[str] = []
        self.cited: dict[str, str] = {}  # current item: relative path -> span id

    def error(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    def parse(self, raw: dict):
        if not self.keys(raw, "$", frozenset({"items"})):
            return (), ()
        if not isinstance(raw["items"], list) or not raw["items"]:
            self.error("items", "must be a non-empty list")
            return (), ()

        items, value_spans = [], []
        for i, obj in enumerate(raw["items"]):
            self.cited = {}
            item = self.item(obj, f"items[{i}]")
            items.append(item)
            value_spans.append(self.cited)
        if self.errors:
            return (), ()
        self.check_lot_ownership(items, value_spans)
        return tuple(items), tuple(value_spans)

    # -- structure -------------------------------------------------------

    def keys(self, obj, path: str, expected: frozenset) -> bool:
        if not isinstance(obj, dict):
            self.error(path, "must be an object")
            return False
        for k in sorted(obj.keys() - expected):
            self.error(path, f"unknown field {k!r}")
        for k in sorted(expected - obj.keys()):
            self.error(path, f"missing field {k!r}")
        return obj.keys() == expected

    def as_list(self, obj, path: str) -> list:
        if not isinstance(obj, list):
            self.error(path, "must be a list")
            return []
        return obj

    def span(self, obj: dict, path: str, required: bool = True) -> Span | None:
        sid = obj["span"]
        if sid is None:
            if required:
                self.error(path, "missing evidence span")
            return None
        span = self.spans.get(sid) if isinstance(sid, str) else None
        if span is None:
            self.error(path, f"cites unknown span {sid!r}")
            return None
        self.cited[path.split(".", 1)[1]] = sid
        return span

    # -- fields ----------------------------------------------------------

    def item(self, obj, path: str) -> NoticeItem | None:
        if not self.keys(obj, path, ITEM_KEYS):
            return None
        before = len(self.errors)
        name = self.text(obj["name"], f"{path}.name", required=True)
        strength = self.strength(obj["strength"], f"{path}.strength")
        form = self.text(obj["form"], f"{path}.form")
        holder = self.text(obj["holder"], f"{path}.holder")
        codes = [
            self.code(c, f"{path}.codes[{j}]")
            for j, c in enumerate(self.as_list(obj["codes"], f"{path}.codes"))
        ]
        lots = [
            self.lot(lot, f"{path}.lots[{j}]")
            for j, lot in enumerate(self.as_list(obj["lots"], f"{path}.lots"))
        ]
        lot_scope = self.lot_scope(obj["lot_scope"], f"{path}.lot_scope", len(lots))
        pack_size = self.pack_size(obj["pack_size"], f"{path}.pack_size")
        if len(self.errors) > before:
            return None
        return NoticeItem(
            name=name,
            strength=strength,
            form=form,
            holder=holder,
            codes=tuple(codes),
            lot_scope=lot_scope,
            lots=tuple(lots),
            pack_size=pack_size,
            evidence_span_ids=tuple(
                sorted(set(self.cited.values()), key=self.order.__getitem__)
            ),
        )

    def text(self, obj, path: str, required: bool = False) -> str | None:
        if obj is None:
            if required:
                self.error(path, "is required")
            return None
        if not self.keys(obj, path, VALUE_KEYS):
            return None
        value = obj["value"]
        if not isinstance(value, str) or not value.strip():
            self.error(path, "value must be a non-empty string")
            return None
        span = self.span(obj, path)
        if span and _fold(value) not in _fold(span.text):
            self.error(path, f"{value!r} does not appear in cited span {span.id}")
        return value

    def identifier(self, obj: dict, path: str, label: str) -> str | None:
        value = obj["value"]
        if not isinstance(value, str) or not value:
            self.error(path, f"{label} must be a non-empty string, copied exactly")
            return None
        span = self.span(obj, path)
        if not appears_verbatim(value, self.source):
            self.error(path, f"{label} {value!r} does not appear in the source text")
        elif span and not appears_verbatim(value, span.text):
            self.error(path, f"{label} {value!r} is not in cited span {span.id}")
        return value

    def code(self, obj, path: str) -> Code | None:
        if not self.keys(obj, path, VALUE_KEYS | {"system"}):
            return None
        system = obj["system"]
        if system not in CODE_SYSTEMS:
            self.error(path, f"system must be one of {sorted(CODE_SYSTEMS)}")
            return None
        value = self.identifier(obj, path, system)
        return Code(system, value) if value is not None else None

    def lot(self, obj, path: str) -> str | None:
        if not self.keys(obj, path, VALUE_KEYS):
            return None
        return self.identifier(obj, path, "lot")

    def lot_scope(self, obj, path: str, n_lots: int) -> LotScope | None:
        if not self.keys(obj, path, VALUE_KEYS):
            return None
        try:
            scope = LotScope(obj["value"])
        except (ValueError, TypeError):
            self.error(path, f"must be one of {[s.value for s in LotScope]}")
            return None
        self.span(obj, path, required=scope is LotScope.ALL_LOTS)
        if scope is LotScope.EXPLICIT_LIST and n_lots == 0:
            self.error(path, "explicit_list needs at least one lot")
        if scope is not LotScope.EXPLICIT_LIST and n_lots:
            self.error(path, f"{scope.value} must not list lots")
        return scope

    def strength(self, obj, path: str) -> Strength | None:
        if obj is None:
            return None
        if not self.keys(obj, path, VALUE_KEYS | {"unit"}):
            return None
        value, unit = obj["value"], obj["unit"]
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            self.error(path, "value must be a positive number")
            return None
        if not isinstance(unit, str) or not unit.strip():
            self.error(path, "unit must be a non-empty string")
            return None
        span = self.span(obj, path)
        pattern = rf"(?<![\d.]){re.escape(f'{value:g}')}\s*{re.escape(unit)}"
        if span and not re.search(pattern, span.text, re.IGNORECASE):
            self.error(
                path, f"{value:g} {unit} does not appear in cited span {span.id}"
            )
        return Strength(float(value), unit)

    def pack_size(self, obj, path: str) -> int | None:
        if obj is None:
            return None
        if not self.keys(obj, path, VALUE_KEYS):
            return None
        value = obj["value"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            self.error(path, "value must be a positive integer")
            return None
        span = self.span(obj, path)
        if span and not re.search(rf"(?<!\d){value}(?!\d)", span.text):
            self.error(path, f"{value} does not appear in cited span {span.id}")
        return value

    # -- cross-item ------------------------------------------------------

    def check_lot_ownership(
        self, items: list[NoticeItem], value_spans: list[dict[str, str]]
    ) -> None:
        """A batch belongs to the nearest product mentioned at or above it.

        Each item's name and code spans are its anchors. If the nearest anchor
        at or before a lot's span belongs only to other items, the lot has been
        attached to the wrong product.
        """
        if len(items) < 2:
            return
        anchors = [
            (self.order[sid], i)
            for i, cited in enumerate(value_spans)
            for key, sid in cited.items()
            if key == "name" or key.startswith("codes[")
        ]
        for i, (item, cited) in enumerate(zip(items, value_spans)):
            for j, lot in enumerate(item.lots):
                sid = cited[f"lots[{j}]"]
                pos = self.order[sid]
                preceding = [a for a in anchors if a[0] <= pos]
                if not preceding:
                    continue
                nearest = max(p for p, _ in preceding)
                owners = {owner for p, owner in preceding if p == nearest}
                if i not in owners:
                    other = items[min(owners)].name
                    self.error(
                        f"items[{i}].lots[{j}]",
                        f"lot {lot!r} in span {sid} is listed under {other!r}, "
                        "not under this product",
                    )


def appears_verbatim(value: str, text: str) -> bool:
    """Exact, case-sensitive match that is not part of a longer identifier."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


def _fold(s: str) -> str:
    """Loose comparison for descriptive text only, never for identifiers."""
    return " ".join(s.split()).casefold()
