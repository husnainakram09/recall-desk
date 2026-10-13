"""Dev 2: five initial matching acceptance tests.

Historical notice identifiers; fictional stock records.
Expected to fail until matching.engine is implemented.
"""

from dataclasses import replace

import pytest

from contracts import (
    Code,
    InventoryRow,
    LotScope,
    MatchState,
    NoticeItem,
    Strength,
)
from matching.engine import classify

# Historical recall scenario: synthetic inventory below.
NOTICE = NoticeItem(
    name="Lercanidipine HCl",
    strength=Strength(value=20.0, unit="mg"),
    form="tablet",
    holder=None,
    codes=(
        Code(system="UK_PL", value="04595/0011"),
        Code(system="GTIN", value="8057742821983"),
    ),
    lot_scope=LotScope.EXPLICIT_LIST,
    lots=("MD4L07",),
    pack_size=28,
    evidence_span_ids=("notice.table1.row1",),
)

STOCK_A = InventoryRow(
    row_id="A",
    location="Shelf A1",
    product_raw="Lercanidipine HCl",
    strength=Strength(value=20.0, unit="mg"),
    form="tablet",
    manufacturer=None,
    holder=None,
    lot_raw="MD4L07",
    expiry_raw="2028-01",
    pack_size=28,
    codes=NOTICE.codes,
    quantity=12,
    unit="pack",
)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param(
            STOCK_A,
            MatchState.EXACT_CANDIDATE,
            id="A-exact-lot",
        ),
        pytest.param(
            replace(STOCK_A, row_id="B", lot_raw="ZZ9TEST"),
            MatchState.NOT_MATCHED,
            id="B-other-lot",
        ),
        pytest.param(
            replace(STOCK_A, row_id="C", lot_raw=None),
            MatchState.NEEDS_EVIDENCE,
            id="C-missing-lot",
        ),
        pytest.param(
            replace(
                STOCK_A,
                row_id="D",
                strength=Strength(value=10.0, unit="mg"),
            ),
            MatchState.CONFLICTING_IDENTIFIERS,
            id="D-label-conflict",
        ),
        pytest.param(
            replace(
                STOCK_A,
                row_id="E",
                product_raw="Different Demo Medicine",
                codes=(
                    Code(system="UK_PL", value="99999/9999"),
                    Code(system="GTIN", value="9999999999999"),
                ),
            ),
            MatchState.NOT_MATCHED,
            id="E-other-product-same-lot",
        ),
    ],
)
def test_five_core_matching_cases(row, expected):
    finding = classify(row, NOTICE)

    assert finding.row_id == row.row_id
    assert finding.state is expected
    assert finding.evidence_span_ids
