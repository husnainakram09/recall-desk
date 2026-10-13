from dataclasses import FrozenInstanceError

import pytest

from contracts import (
    Code,
    Finding,
    InventoryRow,
    LotScope,
    MatchState,
    NoticeItem,
    Strength,
)


def test_contract_dataclasses_are_immutable():
    gtin = Code(system="GTIN", value="05012345678906")
    pl = Code(system="UK_PL", value="PL 12345/0001")
    strength = Strength(value=20.0, unit="mg")

    item = NoticeItem(
        name="Lercanidipine hydrochloride",
        strength=strength,
        form="film-coated tablets",
        holder="Example Pharma Ltd",
        codes=(pl, gtin),
        lot_scope=LotScope.EXPLICIT_LIST,
        lots=("MD4L07",),
        pack_size=28,
        evidence_span_ids=("s1", "s2"),
    )
    row = InventoryRow(
        row_id="C",
        location="Shelf 3B",
        product_raw="lercanidipine 20mg tabs",
        strength=strength,
        form="tablet",
        manufacturer=None,
        holder="Example Pharma Ltd",
        lot_raw=None,
        expiry_raw="2028-01",
        pack_size=28,
        codes=(gtin,),
        quantity=4,
        unit="pack",
    )
    finding = Finding(
        row_id=row.row_id,
        state=MatchState.NEEDS_EVIDENCE,
        matched_fields=("name", "strength", "gtin"),
        missing_fields=("lot",),
        conflicting_fields=(),
        next_evidence="Check the lot number printed on the carton.",
        evidence_span_ids=("s2",),
    )

    for obj, field in [
        (gtin, "value"),
        (strength, "value"),
        (item, "lots"),
        (row, "lot_raw"),
        (finding, "state"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, None)
        hash(obj)
