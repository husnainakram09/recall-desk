"""Pure classification of stock against one reviewed notice item."""

from contracts import Finding, InventoryRow, LotScope, MatchState, NoticeItem
from matching.identity import inspect_identity
from matching.lots import lot_check, near_miss_lot

_CODE_NAMES = {"UK_PL": "PL number", "GTIN": "GTIN"}


def classify(row: InventoryRow, item: NoticeItem) -> Finding:
    lot = lot_check(row.lot_raw, item)
    identity = inspect_identity(
        row,
        item,
        lot_matched=lot == "match" and item.lot_scope is LotScope.EXPLICIT_LIST,
    )

    matched = list(identity.matched)
    missing = list(identity.missing)
    conflicts = list(identity.conflicting)

    def finding(state: MatchState, question: str) -> Finding:
        return Finding(
            row_id=row.row_id,
            state=state,
            matched_fields=tuple(matched),
            missing_fields=tuple(missing),
            conflicting_fields=tuple(conflicts),
            next_evidence=question,
            evidence_span_ids=item.evidence_span_ids,
            descriptive_differences=identity.descriptive_differences,
        )

    if not item.evidence_span_ids or identity.incomplete_codes or lot == "incomplete":
        return finding(
            MatchState.CHECK_INCOMPLETE,
            "Confirm the notice source, identifiers and lot scope.",
        )

    if lot == "match" and not identity.different_product:
        matched.append("lot")

    if identity.different_product:
        return finding(
            MatchState.NOT_MATCHED,
            "Check other notices; this is not a safety clearance.",
        )

    if identity.miskeyed_codes:
        return finding(
            MatchState.CONFLICTING_IDENTIFIERS,
            _miskey_question(row, item, identity.miskeyed_codes),
        )

    if conflicts:
        return finding(
            MatchState.CONFLICTING_IDENTIFIERS,
            "Inspect the conflicting product or pack identifiers.",
        )

    if missing:
        return finding(
            MatchState.NEEDS_EVIDENCE,
            f"Confirm the missing {missing[0]} on the physical pack or record.",
        )

    if lot == "missing":
        missing.append("lot")
        return finding(
            MatchState.NEEDS_EVIDENCE,
            "Read the batch code on the blister or receiving record.",
        )

    if lot == "ambiguous":
        missing.append("lot_scope")
        return finding(
            MatchState.NEEDS_EVIDENCE,
            "Possible batch range or grouped batch expression. "
            "Verify the affected lot scope against the original "
            "notice before excluding this stock record.",
        )

    if lot == "match":
        matched.append("lot_scope")
        return finding(
            MatchState.EXACT_CANDIDATE,
            "Pharmacist must verify the candidate against the source.",
        )

    near = near_miss_lot(row.lot_raw, item)
    if near is not None:
        missing.append("lot")
        return finding(
            MatchState.NEEDS_EVIDENCE,
            f"The recorded batch {row.lot_raw!r} differs from the notice's "
            f"{near!r} only by letter case or O/0, I/1. Read the batch on the "
            "physical pack; it was not corrected automatically.",
        )

    return finding(
        MatchState.NOT_MATCHED,
        "The recorded lot is not listed in this notice. "
        "Check other notices; no match does not establish safety.",
    )


def _miskey_question(
    row: InventoryRow, item: NoticeItem, systems: tuple[str, ...]
) -> str:
    """Name each disagreeing identifier with the stock and notice values."""
    details = []
    for system in systems:
        stock = next((c.value for c in row.codes if c.system == system), None)
        notice = next((c.value for c in item.codes if c.system == system), None)
        details.append(
            f"the recorded {_CODE_NAMES[system]} {stock!r} differs from the "
            f"notice's {notice!r}"
        )
    names = [_CODE_NAMES[s] for s in systems]
    if row.strength and item.strength and row.strength != item.strength:
        details.append(
            f"the recorded strength {row.strength.value:g} {row.strength.unit} "
            f"differs from the notice's {item.strength.value:g} {item.strength.unit}"
        )
        names.append("strength")
    return (
        f"Lot and ingredient match this notice, but {'; '.join(details)}. "
        f"Read the {' and '.join(names)} on the physical pack: it may have "
        "been miskeyed or the pack mislabelled."
    )
