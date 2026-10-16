"""Matching acceptance tests.

The notice uses regulator wording with historical identifiers. Stock rows
use the short form staff type. Stock records are fictional.
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

DESCRIPTIVE = {"product", "form", "holder"}

# MHRA EL(25)A/17, worded as printed on the notice (fixtures/notice_el25a17.txt).
# The notice has no separate form field; "Tablets" comes from its title.
NOTICE = NoticeItem(
    name="Lercanidipine HCl 20mg Tablets",
    strength=Strength(value=20.0, unit="mg"),
    form="Tablets",
    holder="Recordati Industria Chimica e Farmaceutica S.p.A.",
    codes=(
        Code(system="UK_PL", value="PL: 04595/0011"),
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
    codes=(
        Code(system="UK_PL", value="04595/0011"),
        Code(system="GTIN", value="8057742821983"),
    ),
    quantity=12,
    unit="pack",
)

FIVE_CASES = [
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
]


@pytest.mark.parametrize(("row", "expected"), FIVE_CASES)
def test_five_core_matching_cases(row, expected):
    finding = classify(row, NOTICE)

    assert finding.row_id == row.row_id
    assert finding.state is expected
    assert finding.evidence_span_ids
    assert not DESCRIPTIVE & set(finding.missing_fields)
    assert not DESCRIPTIVE & set(finding.conflicting_fields)


# Descriptive fields never decide a state, with one exception: they break the
# tie when the lot matches but every recorded code disagrees (row E's shape).
# That exception is tested on its own below.
NO_TIEBREAK_CASES = FIVE_CASES[:4]


@pytest.mark.parametrize(("row", "expected"), NO_TIEBREAK_CASES)
@pytest.mark.parametrize(
    "name",
    [
        NOTICE.name,
        "LERCANIDIPINE  hydrochloride 20 mg film-coated tablets",
        "Lercan 20",
        "Different Demo Medicine",
        "",
    ],
)
def test_name_only_difference_never_changes_state(row, expected, name):
    finding = classify(replace(row, product_raw=name), NOTICE)

    assert finding.state is expected


@pytest.mark.parametrize(("row", "expected"), NO_TIEBREAK_CASES)
@pytest.mark.parametrize(
    ("form", "holder"),
    [
        (NOTICE.form, NOTICE.holder),
        ("tablet", None),
        (None, "Another Holder Ltd"),
        ("capsule", "Another Holder Ltd"),
    ],
)
def test_form_and_holder_never_change_state(row, expected, form, holder):
    finding = classify(replace(row, form=form, holder=holder), NOTICE)

    assert finding.state is expected


# -- tiebreaker: lot matches, every recorded code disagrees -------------------

SAME_DESCRIPTION = replace(
    STOCK_A,
    product_raw="lercanidipine hydrochloride 20 mg film-coated tablets",
    form=NOTICE.form,
    holder=None,  # not recorded: not a disagreement
)


def test_same_name_matching_lot_wrong_gtin_digit_is_conflict():
    row = replace(
        SAME_DESCRIPTION,
        row_id="T1",
        codes=(Code("UK_PL", "PL 04595/0012"), Code("GTIN", "8057742821984")),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert {"UK_PL", "GTIN"} <= set(finding.conflicting_fields)
    assert "lot" in finding.matched_fields
    assert "'8057742821984'" in finding.next_evidence
    assert "'8057742821983'" in finding.next_evidence
    assert "GTIN" in finding.next_evidence


def test_same_name_matching_lot_no_pl_wrong_gtin_is_conflict():
    row = replace(
        SAME_DESCRIPTION,
        row_id="T2",
        codes=(Code("GTIN", "8057742821984"),),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert finding.conflicting_fields == ("GTIN",)
    assert "UK_PL" in finding.missing_fields
    assert finding.next_evidence.startswith("Lot and ingredient match this notice")
    assert "GTIN '8057742821984'" in finding.next_evidence
    assert "PL number" not in finding.next_evidence


def test_different_name_matching_lot_all_codes_differ_is_not_matched():
    row = FIVE_CASES[4].values[0]  # row E

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.NOT_MATCHED
    assert "lot" not in finding.matched_fields


def test_realistic_staff_wording_with_one_wrong_gtin_digit_is_conflict():
    row = replace(
        STOCK_A,
        row_id="T3",
        product_raw="Lercanidipine HCl",
        form="tablet",
        holder=None,
        lot_raw="MD4L07",
        codes=(Code("GTIN", "8057742821984"),),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert "GTIN '8057742821984'" in finding.next_evidence
    assert "'8057742821983'" in finding.next_evidence


def test_mislabelled_carton_with_other_strength_codes_is_conflict():
    # Carton keyed as the 10 mg product with its own codes; lot is on the notice.
    row = replace(
        STOCK_A,
        row_id="D2",
        product_raw="Lercanidipine HCl 10mg",
        strength=Strength(10.0, "mg"),
        form="tablet",
        codes=(Code("UK_PL", "04595/0010"), Code("GTIN", "8057742821976")),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert "strength 10 mg differs from the notice's 20 mg" in finding.next_evidence


@pytest.mark.parametrize(
    "name",
    ["Amlodipine 5mg tabs", "Nifedipine lercanidipine", "", "Different Demo Medicine"],
)
def test_tiebreak_needs_the_leading_ingredient_to_agree(name):
    row = replace(SAME_DESCRIPTION, product_raw=name)
    row = replace(row, codes=(Code("GTIN", "8057742821984"),))

    assert classify(row, NOTICE).state is MatchState.NOT_MATCHED


@pytest.mark.parametrize(
    ("form", "agrees"),
    [
        ("tablet", True),
        ("Tablets", True),
        ("Film-coated tablets", True),
        ("film coated tablet", True),
        ("capsule", False),
        ("oral solution", False),
    ],
)
def test_tiebreak_form_comparison(form, agrees):
    row = replace(
        STOCK_A,
        product_raw="Lercanidipine HCl",
        form=form,
        codes=(Code("GTIN", "8057742821984"),),
    )
    expected = MatchState.CONFLICTING_IDENTIFIERS if agrees else MatchState.NOT_MATCHED

    assert classify(row, NOTICE).state is expected


def test_tiebreak_recorded_holder_that_disagrees_means_other_product():
    row = replace(
        STOCK_A,
        product_raw="Lercanidipine HCl",
        holder="Another Holder Ltd",
        codes=(Code("GTIN", "8057742821984"),),
    )

    assert classify(row, NOTICE).state is MatchState.NOT_MATCHED


def test_tiebreak_recorded_form_that_disagrees_means_other_product():
    row = replace(
        SAME_DESCRIPTION, form="capsule", codes=(Code("GTIN", "8057742821984"),)
    )

    assert classify(row, NOTICE).state is MatchState.NOT_MATCHED


def test_tiebreak_needs_an_explicitly_listed_lot():
    other_lot = replace(
        SAME_DESCRIPTION, lot_raw="ZZ9TEST", codes=(Code("GTIN", "8057742821984"),)
    )
    all_lots = replace(NOTICE, lot_scope=LotScope.ALL_LOTS, lots=())

    assert classify(other_lot, NOTICE).state is MatchState.NOT_MATCHED
    assert (
        classify(replace(other_lot, lot_raw="MD4L07"), all_lots).state
        is MatchState.NOT_MATCHED
    )


def test_one_matching_code_is_unaffected_by_the_tiebreak():
    row = replace(
        STOCK_A,
        codes=(Code("UK_PL", "04595/0011"), Code("GTIN", "8057742821984")),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert (
        finding.next_evidence == "Inspect the conflicting product or pack identifiers."
    )


def test_descriptive_differences_are_recorded_for_the_reviewer():
    finding = classify(STOCK_A, NOTICE)

    assert finding.state is MatchState.EXACT_CANDIDATE
    assert finding.descriptive_differences == ("product", "form", "holder")


def test_matching_descriptive_wording_is_not_a_difference():
    row = replace(
        STOCK_A,
        product_raw=NOTICE.name.upper(),
        form=NOTICE.form,
        holder=NOTICE.holder,
    )

    finding = classify(row, NOTICE)

    assert finding.descriptive_differences == ()
    assert DESCRIPTIVE <= set(finding.matched_fields)


PL_LABEL_FORMS = [
    "04595/0011",
    "PL: 04595/0011",
    "PL 04595/0011",
    "PL.04595/0011",
    "PL04595/0011",
    "PL : 04595/0011",
    "PL. 04595/0011",
    "  PL:  04595/0011 ",
]


@pytest.mark.parametrize("notice_pl", PL_LABEL_FORMS)
@pytest.mark.parametrize("stock_pl", PL_LABEL_FORMS)
def test_pl_label_forms_compare_equal_on_both_sides(notice_pl, stock_pl):
    item = replace(NOTICE, codes=(Code("UK_PL", notice_pl), NOTICE.codes[1]))
    row = replace(STOCK_A, codes=(Code("UK_PL", stock_pl), STOCK_A.codes[1]))

    finding = classify(row, item)

    assert finding.state is MatchState.EXACT_CANDIDATE
    assert "UK_PL" in finding.matched_fields
    assert row.codes[0].value == stock_pl  # raw values kept for display
    assert item.codes[0].value == notice_pl


@pytest.mark.parametrize("notice_pl", ["PL: 04595/0011", "PL.04595/0011"])
@pytest.mark.parametrize(("row", "expected"), FIVE_CASES[:3])
def test_rows_a_to_c_unaffected_by_labelled_notice_pl(notice_pl, row, expected):
    item = replace(NOTICE, codes=(Code("UK_PL", notice_pl), NOTICE.codes[1]))

    assert classify(row, item).state is expected


@pytest.mark.parametrize(
    "stock_pl",
    [
        "4595/0011",
        "PL: 4595/0011",
        "PL 04595/0012",
        "pl 04595/0011",
        "PLGB 04595/0011",
    ],
)
def test_pl_digits_and_other_spellings_still_compared_exactly(stock_pl):
    row = replace(
        STOCK_A,
        codes=(Code("UK_PL", stock_pl), STOCK_A.codes[1]),
    )

    finding = classify(row, NOTICE)

    assert finding.state is MatchState.CONFLICTING_IDENTIFIERS
    assert "UK_PL" in finding.conflicting_fields


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


def test_same_codes_different_name_is_informational_only():
    row = replace(STOCK_A, product_raw="Different Demo Medicine")
    finding = classify(row, NOTICE)

    assert finding.state is MatchState.EXACT_CANDIDATE
    assert "product" in finding.descriptive_differences


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


@pytest.mark.parametrize(
    ("stock_lot", "expected"),
    [
        pytest.param(
            "AB-123",
            MatchState.EXACT_CANDIDATE,
            id="listed-exact-batch",
        ),
        pytest.param(
            "MD4L09",
            MatchState.NEEDS_EVIDENCE,
            id="possible-range-member",
        ),
        pytest.param(
            "ZZ9TEST",
            MatchState.NEEDS_EVIDENCE,
            id="unresolved-range-prevents-exclusion",
        ),
    ],
)
def test_mixed_exact_lot_and_unresolved_range(stock_lot, expected):
    item = replace(
        NOTICE,
        lots=("AB-123", "MD4L07 to MD4L10"),
    )
    row = replace(STOCK_A, lot_raw=stock_lot)

    finding = classify(row, item)

    assert finding.state is expected

    if expected is MatchState.EXACT_CANDIDATE:
        assert "lot" in finding.matched_fields
    else:
        assert "lot_scope" in finding.missing_fields
