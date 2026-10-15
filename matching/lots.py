"""Conservative handling of exact lots and ambiguous ranges."""

import re

from contracts import LotScope, NoticeItem

# Explicit range markers; ASCII hyphens need separate handling.
_RANGE_MARKER = re.compile(
    r"\s+(?:to|through|thru)\s+|\s+-\s+|[–—]",
    flags=re.IGNORECASE,
)


def _possible_range(value: str) -> bool:
    """Flag likely ranges without attempting to interpret them."""
    value = value.strip()

    if _RANGE_MARKER.search(value):
        return True

    # A compact expression like MD4L07-MD4L10 may be a range.
    # AB-123 is treated as a literal identifier instead.
    if value.count("-") == 1:
        left, right = value.split("-", 1)

        if (
            left
            and right
            and any(ch.isdigit() for ch in left)
            and any(ch.isdigit() for ch in right)
        ):
            return True

    return False


def lot_check(lot_raw: str | None, item: NoticeItem) -> str:
    """Return match, different, missing, ambiguous or incomplete."""
    if item.lot_scope is LotScope.UNSPECIFIED:
        return "incomplete"

    if item.lot_scope is LotScope.ALL_LOTS:
        return "match"

    if item.lot_scope is not LotScope.EXPLICIT_LIST or not item.lots:
        return "incomplete"

    notice_lots = tuple(lot.strip() for lot in item.lots)

    if any(not lot for lot in notice_lots):
        return "incomplete"

    if lot_raw is None or not lot_raw.strip():
        return "missing"

    stock_lot = lot_raw.strip()

    if _possible_range(stock_lot):
        return "ambiguous"

    # Trust exact literal identifiers only, not range expressions.
    if any(
        stock_lot == lot and not _possible_range(lot)
        for lot in notice_lots
    ):
        return "match"

    # A non-exact stock lot might belong to an unresolved range.
    if any(_possible_range(lot) for lot in notice_lots):
        return "ambiguous"

    return "different"
