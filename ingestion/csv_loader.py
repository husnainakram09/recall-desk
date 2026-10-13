"""Stock CSV -> InventoryRow. Bad rows are reported, never raised or dropped silently."""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from contracts import Code, InventoryRow, Strength
from ingestion.normalise import cell, parse_expiry, parse_int, parse_positive_float

COLUMNS = (
    "row_id",
    "site",
    "location",
    "product",
    "strength_mg",
    "dosage_form",
    "manufacturer",
    "holder",
    "lot",
    "expiry",
    "pack_size",
    "quantity",
    "unit",
    "pl",
    "gtin",
)


@dataclass(frozen=True)
class RowError:
    line: int  # line in the CSV file; the header is line 1
    row_id: str | None
    message: str


@dataclass
class LoadResult:
    rows: list[InventoryRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    # (line, cells as read) for every data row, good or bad, for previews
    raw_records: list[tuple[int, dict[str, str]]] = field(default_factory=list)


def load_inventory_csv(path: str | Path) -> LoadResult:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return parse_inventory_csv(f.read())


def parse_inventory_csv(text: str) -> LoadResult:
    result = LoadResult()
    # Every cell is read as text; nothing is type-converted by the csv module.
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    header = reader.fieldnames or []

    missing = [c for c in COLUMNS if c not in header]
    if missing:
        result.errors.append(RowError(1, None, f"missing column(s): {missing}"))
        return result
    for extra in (c for c in header if c not in COLUMNS):
        result.errors.append(RowError(1, None, f"unknown column {extra!r} ignored"))

    seen_ids: set[str] = set()
    for record in reader:
        line = reader.line_num
        result.raw_records.append(
            (line, {k: v for k, v in record.items() if k in COLUMNS})
        )
        row_id = cell(record["row_id"])
        problems = []
        if None in record:
            problems.append("row has more cells than the header")
        if row_id is not None and row_id in seen_ids:
            problems.append(f"duplicate row_id {row_id!r}")
        row = _parse_row(record, problems)
        if problems:
            result.errors.extend(RowError(line, row_id, p) for p in problems)
        else:
            seen_ids.add(row.row_id)
            result.rows.append(row)
    return result


def _parse_row(record: dict, problems: list[str]) -> InventoryRow | None:
    def required(column: str) -> str | None:
        value = cell(record[column])
        if value is None:
            problems.append(f"{column} is required")
        return value

    def parsed(fn, *args):
        try:
            return fn(*args)
        except ValueError as exc:
            problems.append(str(exc))
            return None

    row_id = required("row_id")
    product = required("product")
    unit = required("unit")
    location = _location(cell(record["site"]), cell(record["location"]))
    if location is None:
        problems.append("site or location is required")

    quantity = parsed(parse_int, record["quantity"], "quantity")
    if quantity is None and cell(record["quantity"]) is None:
        problems.append("quantity is required")
    strength_mg = parsed(parse_positive_float, record["strength_mg"], "strength_mg")
    pack_size = parsed(parse_int, record["pack_size"], "pack_size")
    expiry = parsed(parse_expiry, record["expiry"])

    if problems:
        return None

    codes = tuple(
        Code(system, value)
        for system, value in (
            ("UK_PL", cell(record["pl"])),
            ("GTIN", cell(record["gtin"])),
        )
        if value is not None
    )
    return InventoryRow(
        row_id=row_id,
        location=location,
        product_raw=product,
        strength=Strength(strength_mg, "mg") if strength_mg is not None else None,
        form=cell(record["dosage_form"]),
        manufacturer=cell(record["manufacturer"]),
        holder=cell(record["holder"]),
        lot_raw=cell(record["lot"]),
        expiry_raw=expiry,
        pack_size=pack_size,
        codes=codes,
        quantity=quantity,
        unit=unit,
    )


def _location(site: str | None, location: str | None) -> str | None:
    # InventoryRow has no site field, so site is kept as a prefix of location.
    if site is not None and location is not None:
        return f"{site} / {location}"
    return site or location
