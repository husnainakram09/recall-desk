"""Integration: Dev 1 CSV ingestion -> Dev 2 matching."""

import csv
import io

import pytest

from contracts import (
    Code,
    LotScope,
    MatchState,
    NoticeItem,
    Strength,
)
from ingestion.csv_loader import COLUMNS, parse_inventory_csv
from matching.engine import classify

NOTICE = NoticeItem(
    name="Lercanidipine HCl",
    strength=Strength(20.0, "mg"),
    form="tablet",
    holder=None,
    codes=(
        Code("UK_PL", "04595/0011"),
        Code("GTIN", "8057742821983"),
    ),
    lot_scope=LotScope.EXPLICIT_LIST,
    lots=("MD4L07",),
    pack_size=28,
    evidence_span_ids=("S1",),
)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"row_id": "A"}, MatchState.EXACT_CANDIDATE),
        (
            {"row_id": "B", "lot": "ZZ9TEST"},
            MatchState.NOT_MATCHED,
        ),
        (
            {"row_id": "C", "lot": ""},
            MatchState.NEEDS_EVIDENCE,
        ),
        (
            {"row_id": "D", "strength_mg": "10"},
            MatchState.CONFLICTING_IDENTIFIERS,
        ),
        (
            {
                "row_id": "E",
                "product": "Different Demo Medicine",
                "pl": "99999/9999",
                "gtin": "9999999999999",
            },
            MatchState.NOT_MATCHED,
        ),
    ],
)
def test_csv_to_matching_pipeline(changes, expected):
    record = dict.fromkeys(COLUMNS, "")
    record.update(
        row_id="A",
        site="DEMO",
        location="A1",
        product="Lercanidipine HCl",
        strength_mg="20",
        dosage_form="tablet",
        lot="MD4L07",
        expiry="2028-01",
        pack_size="28",
        quantity="12",
        unit="pack",
        pl="04595/0011",
        gtin="8057742821983",
    )
    record.update(changes)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerow(record)

    parsed = parse_inventory_csv(output.getvalue())

    assert parsed.errors == []
    assert len(parsed.rows) == 1

    row = parsed.rows[0]
    finding = classify(row, NOTICE)

    assert finding.row_id == record["row_id"]
    assert finding.state is expected
    assert finding.evidence_span_ids == ("S1",)
