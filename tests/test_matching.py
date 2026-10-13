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


def test_no_notice_codes_incomplete():
    item = replace(NOTICE, codes=())
    assert classify(STOCK_A, item).state is MatchState.CHECK_INCOMPLETE


def test_no_scope_incomplete():
    item = replace(NOTICE, lot_scope=LotScope.UNSPECIFIED)
    assert classify(STOCK_A, item).state is MatchState.CHECK_INCOMPLETE


def test_missing_code_needs_evidence():
    row = replace(
        STOCK_A,
        codes=(Code("UK_PL", "04595/0011"),),
    )
    assert classify(row, NOTICE).state is MatchState.NEEDS_EVIDENCE


def test_same_codes_different_name_conflict():
    row = replace(STOCK_A, product_raw="Different Demo Medicine")
    assert classify(row, NOTICE).state is MatchState.CONFLICTING_IDENTIFIERS


def test_all_lots_explicit():
    item = replace(NOTICE, lot_scope=LotScope.ALL_LOTS, lots=())
    row = replace(STOCK_A, lot_raw=None)
    assert classify(row, item).state is MatchState.EXACT_CANDIDATE


def test_leading_zero_preserved():
    item = replace(NOTICE, lots=("00123",))
    row = replace(STOCK_A, lot_raw="123")
    assert classify(row, item).state is MatchState.NOT_MATCHED


def test_conflicting_codes_one_match():
    row = replace(
        STOCK_A,
        codes=(
            Code("UK_PL", "04595/0011"),
            Code("GTIN", "WRONG"),
        ),
    )
    assert classify(row, NOTICE).state is MatchState.CONFLICTING_IDENTIFIERS

def test_matching_lot_visible_despite_strength_conflict():
    row = replace(
        STOCK_A,
        row_id="D2",
        strength=Strength(10.0, "mg"),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert "lot" in finding.matched_fields
    assert "strength" in finding.conflicting_fields


def test_other_lot_explanation_is_specific():
    row = replace(
        STOCK_A,
        row_id="B2",
        lot_raw="ZZ9TEST",
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.NOT_MATCHED
    assert "lot" in finding.next_evidence.lower()
    assert "safety" in finding.next_evidence.lower()

def test_unsupported_lot_range_needs_evidence():
    item = replace(
        NOTICE,
        lots=("MD4L07 to MD4L10",),
    )

    row = replace(
        STOCK_A,
        row_id="RANGE-01",
        lot_raw="MD4L08",
    )

    finding = classify(row, item)

    assert finding.state is MatchState.NEEDS_EVIDENCE


def test_literal_hyphenated_batch_can_match():
    item = replace(NOTICE, lots=("AB-123",))
    row = replace(STOCK_A, lot_raw="AB-123")

    finding = classify(row, item)

    assert finding.state is MatchState.EXACT_CANDIDATE


def test_literal_hyphenated_batch_can_be_excluded():
    item = replace(NOTICE, lots=("AB-123",))
    row = replace(STOCK_A, lot_raw="AB-124")

    finding = classify(row, item)

    assert finding.state is MatchState.NOT_MATCHED


def test_compact_range_needs_evidence():
    item = replace(NOTICE, lots=("MD4L07-MD4L10",))
    row = replace(STOCK_A, lot_raw="MD4L08")

    finding = classify(row, item)

    assert finding.state is MatchState.NEEDS_EVIDENCE
    assert "lot_scope" in finding.missing_fields


def test_unicode_dash_range_needs_evidence():
    item = replace(NOTICE, lots=("MD4L07–MD4L10",))
    row = replace(STOCK_A, lot_raw="MD4L08")

    finding = classify(row, item)

    assert finding.state is MatchState.NEEDS_EVIDENCE
