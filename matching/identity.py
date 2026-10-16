"""Tiered product identity checks; no AI or network.

AUTHORITATIVE  UK_PL, GTIN (lots are checked in matching.lots).
               A disagreement is a conflict; a gap needs evidence.
SIGNIFICANT    strength, pack_size.
               A disagreement is a conflict; a gap needs evidence.
DESCRIPTIVE    product name, form, holder.
               Reported to the reviewer. Never a conflict and never missing
               evidence on their own. Their only effect on state is the
               tiebreaker in inspect_identity: lot matched, every recorded
               code disagrees.
"""

import re
from dataclasses import dataclass

from contracts import InventoryRow, NoticeItem


def _label(value: str) -> str:
    return " ".join(value.casefold().split())


# An optional leading "PL" label followed by any spaces, colons or full stops:
# "PL: 04595/0011", "PL 04595/0011", "PL.04595/0011", "PL04595/0011".
_PL_LABEL = re.compile(r"^PL[\s:.]*")


def _code_key(system: str, value: str) -> str:
    """Comparison key only. Code.value keeps the raw text for display.

    A PL number is compared without surrounding whitespace or a leading
    "PL" label. Digits, leading zeros and the slash are compared exactly.
    Every other code is compared exactly as written.
    """
    if system == "UK_PL":
        value = _PL_LABEL.sub("", value.strip()).strip()
    return value


@dataclass(frozen=True)
class IdentityCheck:
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    conflicting: tuple[str, ...]
    descriptive_differences: tuple[str, ...]
    different_product: bool
    incomplete_codes: bool
    # Codes the tiebreaker judged miskeyed on the notice's own product.
    miskeyed_codes: tuple[str, ...] = ()


def _name_tokens(value: str) -> list[str]:
    return [t.strip(".,;:()[]") for t in value.casefold().split()]


def _form_words(value: str) -> set[str]:
    """ "Film-coated Tablets" -> {"film", "coated", "tablet"}. Plural s dropped."""
    words = re.split(r"[\s\-/]+", value.casefold())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w}


def _recorded(value: str | None) -> bool:
    return bool(value and value.strip())


def _descriptive_agrees(row: InventoryRow, item: NoticeItem) -> bool:
    """Staff wording agrees with the notice title for the tiebreaker only.

    - Ingredient: the stock name's first token appears among the notice
      title's tokens ("Lercanidipine HCl" agrees with "Lercanidipine
      Hydrochloride 20 mg Film-coated Tablets").
    - Form: one side's words contain the other's ("tablet" agrees with
      "film-coated tablet"; "capsule" does not).
    - Holder: compared as written, ignoring case and spacing.
    A form or holder the stock row does not record is not a disagreement.
    """
    stock_tokens = _name_tokens(row.product_raw)
    if not stock_tokens or stock_tokens[0] not in _name_tokens(item.name):
        return False
    if _recorded(row.form) and _recorded(item.form):
        stock_form, notice_form = _form_words(row.form), _form_words(item.form)
        if not (stock_form <= notice_form or notice_form <= stock_form):
            return False
    return not (
        _recorded(row.holder)
        and _recorded(item.holder)
        and _label(row.holder) != _label(item.holder)
    )


def inspect_identity(
    row: InventoryRow, item: NoticeItem, lot_matched: bool = False
) -> IdentityCheck:
    """lot_matched: the stock lot is literally on the notice's explicit list."""
    matched: list[str] = []
    missing: list[str] = []
    conflicting: list[str] = []
    descriptive: list[str] = []

    notice_codes = {}
    row_codes = {}

    for code in item.codes:
        key = _code_key(code.system, code.value)
        if code.system in notice_codes and notice_codes[code.system] != key:
            conflicting.append(f"duplicate_notice_{code.system}")
        notice_codes[code.system] = key

    for code in row.codes:
        key = _code_key(code.system, code.value)
        if code.system in row_codes and row_codes[code.system] != key:
            conflicting.append(f"duplicate_stock_{code.system}")
        row_codes[code.system] = key

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

    for field, observed, expected in (
        ("strength", row.strength, item.strength),
        ("pack_size", row.pack_size, item.pack_size),
    ):
        if expected is None:
            continue

        if observed is None:
            missing.append(field)
        elif field == "strength":
            if observed.value == expected.value and _label(observed.unit) == _label(
                expected.unit
            ):
                matched.append(field)
            else:
                conflicting.append(field)
        elif observed == expected:
            matched.append(field)
        else:
            conflicting.append(field)

    for field, observed, expected in (
        ("product", row.product_raw, item.name),
        ("form", row.form, item.form),
        ("holder", row.holder, item.holder),
    ):
        if expected is None or not expected.strip():
            continue

        if observed and observed.strip() and _label(observed) == _label(expected):
            matched.append(field)
        else:
            descriptive.append(field)

    codes_disagree = matching_codes == 0 and different_codes > 0

    # Tiebreaker for one ambiguity only: the lot already matched, yet every
    # recorded code disagrees. Agreeing descriptive fields point to a
    # miskeyed code on the notice's product (a conflict for a human to
    # inspect). Otherwise it is a different product sharing a lot string
    # (row E). Everywhere else, codes alone decide "different product".
    miskeyed = codes_disagree and lot_matched and _descriptive_agrees(row, item)
    different_product = codes_disagree and not miskeyed

    return IdentityCheck(
        tuple(matched),
        tuple(missing),
        tuple(conflicting),
        tuple(descriptive),
        different_product,
        not bool(notice_codes),
        tuple(s for s in conflicting if s in ("UK_PL", "GTIN")) if miskeyed else (),
    )
