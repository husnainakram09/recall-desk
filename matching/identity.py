"""Conservative product identity checks; no AI or network."""

from dataclasses import dataclass

from contracts import InventoryRow, NoticeItem


def _label(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class IdentityCheck:
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    conflicting: tuple[str, ...]
    different_product: bool
    incomplete_codes: bool


def inspect_identity(row: InventoryRow, item: NoticeItem) -> IdentityCheck:
    matched: list[str] = []
    missing: list[str] = []
    conflicting: list[str] = []

    notice_codes = {}
    row_codes = {}

    for code in item.codes:
        if code.system in notice_codes and notice_codes[code.system] != code.value:
            conflicting.append(f"duplicate_notice_{code.system}")
        notice_codes[code.system] = code.value

    for code in row.codes:
        if code.system in row_codes and row_codes[code.system] != code.value:
            conflicting.append(f"duplicate_stock_{code.system}")
        row_codes[code.system] = code.value

    matching_codes = 0
    different_codes = 0

    for system, expected in notice_codes.items():
        observed = row_codes.get(system)

        if not observed:
            missing.append(system)
        elif observed == expected:
            matched.append(system)
            matching_codes += 1
        else:
            conflicting.append(system)
            different_codes += 1

    same_name = bool(row.product_raw.strip() and item.name.strip()) and (
        _label(row.product_raw) == _label(item.name)
    )

    if not row.product_raw.strip():
        missing.append("product")
    elif same_name:
        matched.append("product")
    else:
        conflicting.append("product")

    for field, observed, expected in (
        ("strength", row.strength, item.strength),
        ("form", row.form, item.form),
        ("holder", row.holder, item.holder),
        ("pack_size", row.pack_size, item.pack_size),
    ):
        if expected is None:
            continue

        if observed is None or observed == "":
            missing.append(field)
        elif field == "strength":
            if (
                observed.value == expected.value
                and _label(observed.unit) == _label(expected.unit)
            ):
                matched.append(field)
            else:
                conflicting.append(field)
        elif isinstance(observed, str):
            if _label(observed) == _label(expected):
                matched.append(field)
            else:
                conflicting.append(field)
        elif observed == expected:
            matched.append(field)
        else:
            conflicting.append(field)

    different_product = (
        not same_name
        and bool(row.product_raw.strip())
        and matching_codes == 0
        and different_codes > 0
    )

    return IdentityCheck(
        tuple(matched),
        tuple(missing),
        tuple(conflicting),
        different_product,
        not bool(notice_codes),
    )
