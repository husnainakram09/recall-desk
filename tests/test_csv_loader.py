from contracts import Code, Strength
from ingestion.csv_loader import parse_inventory_csv

HEADER = (
    "row_id,site,location,product,strength_mg,dosage_form,manufacturer,holder,"
    "lot,expiry,pack_size,quantity,unit,pl,gtin\n"
)


def _load(*rows: str):
    return parse_inventory_csv(HEADER + "\n".join(rows) + "\n")


def test_leading_zeros_are_kept_in_identifiers():
    result = _load(
        "A,Site 1,Shelf 3B,Lercanidipine 20mg tabs,20,tablet,Maker Ltd,Holder Ltd,"
        "007123,2028-01,028,4,pack,PL 01234/0056,05012345678906"
    )

    assert result.errors == []
    row = result.rows[0]
    assert row.lot_raw == "007123"
    assert row.codes == (
        Code("UK_PL", "PL 01234/0056"),
        Code("GTIN", "05012345678906"),
    )
    assert row.expiry_raw == "2028-01"
    assert row.pack_size == 28
    assert row.strength == Strength(20.0, "mg")
    assert row.location == "Site 1 / Shelf 3B"
    assert (row.manufacturer, row.holder) == ("Maker Ltd", "Holder Ltd")


def test_empty_lot_becomes_none():
    result = _load(
        "C,Site 1,Shelf 3B,Lercanidipine 20mg tabs,20,tablet,,,,,,4,pack,,  ",
    )

    assert result.errors == []
    row = result.rows[0]
    assert row.lot_raw is None
    assert row.manufacturer is None
    assert row.holder is None
    assert row.expiry_raw is None
    assert row.codes == ()


def test_lot_with_letter_o_and_digit_zero_is_preserved_exactly():
    result = _load(
        "D,Site 1,Shelf 3B,Lercanidipine 20mg tabs,20,tablet,,,"
        "MD4LO7-0o,2028-01,28,4,pack,,"
    )

    assert result.errors == []
    assert result.rows[0].lot_raw == "MD4LO7-0o"


def test_bad_rows_are_reported_alongside_good_rows():
    result = _load(
        "A,Site 1,Shelf 3B,Lercanidipine 20mg tabs,20,tablet,,,MD4L07,2028-01,28,4,pack,,",
        "B,Site 1,Shelf 3B,Lercanidipine 20mg tabs,20,tablet,,,ZZ9TEST,01/2028,28,four,pack,,",
    )

    assert [r.row_id for r in result.rows] == ["A"]
    assert {(e.line, e.row_id) for e in result.errors} == {(3, "B")}
    assert len(result.errors) == 2  # bad expiry and bad quantity
