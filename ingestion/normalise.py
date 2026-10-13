"""Cell-level parsing for stock CSVs. Identifiers are preserved as typed.

Nothing here strips, upper-cases or otherwise rewrites an identifier. A cell
that is empty or only whitespace becomes None; any other text cell comes back
exactly as it appeared. Only numeric and date cells are parsed, and a cell
that does not parse cleanly is an error, never a guess.
"""

import re

_WHOLE = re.compile(r"\d+")
_DECIMAL = re.compile(r"\d+(\.\d+)?")
_YEAR_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def cell(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


def parse_int(value: str | None, field: str) -> int | None:
    if cell(value) is None:
        return None
    if not _WHOLE.fullmatch(value.strip()):
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    return int(value.strip())


def parse_positive_float(value: str | None, field: str) -> float | None:
    if cell(value) is None:
        return None
    if not _DECIMAL.fullmatch(value.strip()) or float(value) <= 0:
        raise ValueError(f"{field} must be a positive number, got {value!r}")
    return float(value)


def parse_expiry(value: str | None) -> str | None:
    """Month precision only, as YYYY-MM. No day is invented or kept."""
    if cell(value) is None:
        return None
    if not _YEAR_MONTH.fullmatch(value.strip()):
        raise ValueError(f"expiry must be YYYY-MM, got {value!r}")
    return value.strip()
