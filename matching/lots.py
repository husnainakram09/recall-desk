"""Exact lot scope handling; never guess ranges or coerce identifiers."""

from contracts import LotScope, NoticeItem


def lot_check(lot_raw: str | None, item: NoticeItem) -> str:
    """Return match, different, missing, or incomplete."""

    if item.lot_scope is LotScope.UNSPECIFIED:
        return "incomplete"

    if item.lot_scope is LotScope.ALL_LOTS:
        return "match"

    if item.lot_scope is not LotScope.EXPLICIT_LIST or not item.lots:
        return "incomplete"

    if lot_raw is None or not lot_raw.strip():
        return "missing"

    # Keep O/0, leading zeros, case and punctuation unchanged.
    return "match" if lot_raw.strip() in item.lots else "different"
