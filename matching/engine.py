"""Pure classification of stock against one reviewed notice item."""

from contracts import Finding, InventoryRow, MatchState, NoticeItem
from matching.identity import inspect_identity
from matching.lots import lot_check


def classify(row: InventoryRow, item: NoticeItem) -> Finding:
    identity = inspect_identity(row, item)
    lot = lot_check(row.lot_raw, item)

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
        )

    if (
        not item.evidence_span_ids
        or identity.incomplete_codes
        or lot == "incomplete"
    ):
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

    if lot == "match":
        matched.append("lot_scope")
        return finding(
            MatchState.EXACT_CANDIDATE,
            "Pharmacist must verify the candidate against the source.",
        )

    return finding(
        MatchState.NOT_MATCHED,
        "The recorded lot is not listed in this notice. "
        "Check other notices; no match does not establish safety.",
    )
