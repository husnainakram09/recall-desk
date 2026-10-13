import copy

import pytest

from contracts import Code, LotScope, Strength
from extraction.spans import split_spans
from extraction.validate import NoticeValidationError, extract_notice, parse_notice

# Synthetic text for unit tests. Not issued by any regulator.
SOURCE = """\
TEST NOTICE - synthetic text for unit tests, not issued by any regulator
Example Pharma Ltd
Lercanidipine hydrochloride 10 mg film-coated tablets, PL 12345/0001, GTIN 05012345678906
Batch: AB12C3, expiry 01/2028, pack size 28

Lercanidipine hydrochloride 20 mg film-coated tablets, PL 12345/0002, GTIN 05012345678913
Batch: MD4L07, expiry 03/2028, pack size 28
"""
SPANS = split_spans(SOURCE)  # S1 title, S2 holder, S3/S4 10 mg, S5/S6 20 mg


def _item(mg, pl, gtin, product_span, lot, lot_span):
    return {
        "name": {
            "value": f"Lercanidipine hydrochloride {mg} mg film-coated tablets",
            "span": product_span,
        },
        "strength": {"value": mg, "unit": "mg", "span": product_span},
        "form": {"value": "film-coated tablets", "span": product_span},
        "holder": {"value": "Example Pharma Ltd", "span": "S2"},
        "codes": [
            {"system": "UK_PL", "value": pl, "span": product_span},
            {"system": "GTIN", "value": gtin, "span": product_span},
        ],
        "lot_scope": {"value": "explicit_list", "span": lot_span},
        "lots": [{"value": lot, "span": lot_span}],
        "pack_size": {"value": 28, "span": lot_span},
    }


def good_response():
    return {
        "items": [
            _item(10, "PL 12345/0001", "05012345678906", "S3", "AB12C3", "S4"),
            _item(20, "PL 12345/0002", "05012345678913", "S5", "MD4L07", "S6"),
        ]
    }


class FakeAdapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []

    def extract(self, text):
        self.messages.append(text)
        return self.responses.pop(0)


def test_good_response_parses_into_notice_items():
    result = extract_notice(FakeAdapter(good_response()), SOURCE)

    assert result.attempts == 1
    first, second = result.items
    assert first.strength == Strength(10.0, "mg")
    assert first.codes == (
        Code("UK_PL", "PL 12345/0001"),
        Code("GTIN", "05012345678906"),
    )
    assert first.lot_scope is LotScope.EXPLICIT_LIST
    assert first.lots == ("AB12C3",)
    assert first.pack_size == 28
    assert first.evidence_span_ids == ("S2", "S3", "S4")
    assert second.lots == ("MD4L07",)
    assert result.value_spans[1]["lots[0]"] == "S6"


def test_altered_gtin_digit_is_flagged():
    raw = good_response()
    raw["items"][0]["codes"][1]["value"] = "05012345678907"

    _, _, errors = parse_notice(raw, SPANS)

    assert any(
        "items[0].codes[1]" in e and "does not appear in the source text"
        for e in errors
    )


def test_unknown_field_is_rejected():
    raw = good_response()
    raw["items"][0]["advice"] = {"value": "Stop taking this medicine", "span": "S1"}

    _, _, errors = parse_notice(raw, SPANS)

    assert errors == ["items[0]: unknown field 'advice'"]


def test_lots_attached_to_wrong_product_are_flagged():
    raw = good_response()
    first, second = raw["items"]
    first["lots"], second["lots"] = (
        copy.deepcopy(second["lots"]),
        copy.deepcopy(first["lots"]),
    )

    _, _, errors = parse_notice(raw, SPANS)

    assert any("items[0].lots[0]" in e and "'MD4L07'" in e for e in errors)
    assert any("items[1].lots[0]" in e and "'AB12C3'" in e for e in errors)


def test_retry_passes_errors_back_then_succeeds():
    bad = good_response()
    bad["items"][0]["codes"][1]["value"] = "05012345678907"
    adapter = FakeAdapter(bad, good_response())

    result = extract_notice(adapter, SOURCE)

    assert result.attempts == 2
    assert "05012345678907" in adapter.messages[1]
    assert "VALIDATION_ERRORS" in adapter.messages[1]


def test_second_failure_raises_for_manual_draft():
    bad = good_response()
    bad["items"][0]["lots"][0]["value"] = "AB12CЗ"  # Cyrillic Ze, not digit 3
    adapter = FakeAdapter(bad, copy.deepcopy(bad))

    with pytest.raises(NoticeValidationError) as exc:
        extract_notice(adapter, SOURCE)

    assert exc.value.raw == bad
    assert any("does not appear in the source text" in e for e in exc.value.errors)
