"""Shared data contract between Dev 1 (ingestion, extraction) and Dev 2 (matching).

Frozen after 13 Oct 2026. Do not change without both devs agreeing.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Code:
    system: str  # "UK_PL" | "GTIN"
    value: str  # raw, leading zeros kept


@dataclass(frozen=True)
class Strength:
    value: float
    unit: str  # "mg"


class LotScope(Enum):
    EXPLICIT_LIST = "explicit_list"
    ALL_LOTS = "all_lots"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class NoticeItem:
    name: str
    strength: Optional[Strength]
    form: Optional[str]
    holder: Optional[str]
    codes: tuple[Code, ...]
    lot_scope: LotScope
    lots: tuple[str, ...]
    pack_size: Optional[int]
    evidence_span_ids: tuple[str, ...]


@dataclass(frozen=True)
class InventoryRow:
    row_id: str
    location: str
    product_raw: str  # exactly as typed by staff
    strength: Optional[Strength]
    form: Optional[str]
    manufacturer: Optional[str]
    holder: Optional[str]
    lot_raw: Optional[str]  # None means absent, not ""
    expiry_raw: Optional[str]  # "2028-01", month precision
    pack_size: Optional[int]
    codes: tuple[Code, ...]
    quantity: int
    unit: str  # "pack"


class MatchState(Enum):
    EXACT_CANDIDATE = "exact_candidate"
    NEEDS_EVIDENCE = "needs_evidence"
    CONFLICTING_IDENTIFIERS = "conflicting_identifiers"
    NOT_MATCHED = "not_matched_to_this_notice"
    CHECK_INCOMPLETE = "check_incomplete"


@dataclass(frozen=True)
class Finding:
    row_id: str
    state: MatchState
    matched_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    conflicting_fields: tuple[str, ...]
    next_evidence: Optional[str]
    evidence_span_ids: tuple[str, ...]
