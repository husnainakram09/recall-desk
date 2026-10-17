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


# Characters staff commonly confuse when reading or typing a batch code.
_CONFUSABLE = str.maketrans({"o": "0", "i": "1"})


def _confusable_key(value: str) -> str:
    return value.strip().casefold().translate(_CONFUSABLE)


def near_miss_lot(lot_raw: str | None, item: NoticeItem) -> str | None:
    """The listed lot that the stock lot matches only after ignoring letter
    case and O/0, I/1 differences, or None.

    Used to flag a likely typo for a person to check. The recorded lot is
    never corrected: it stays exactly as typed.
    """
    if item.lot_scope is not LotScope.EXPLICIT_LIST:
        return None
    if lot_raw is None or not lot_raw.strip():
        return None
    key = _confusable_key(lot_raw)
    for lot in item.lots:
        if lot.strip() != lot_raw.strip() and _confusable_key(lot) == key:
            return lot
    return None


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
    if any(stock_lot == lot and not _possible_range(lot) for lot in notice_lots):
        return "match"

    # A non-exact stock lot might belong to an unresolved range.
    if any(_possible_range(lot) for lot in notice_lots):
        return "ambiguous"

    return "different"
