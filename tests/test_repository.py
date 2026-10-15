"""Persistence and revision integrity tests."""

from dataclasses import replace

import pytest

from contracts import (
    Code,
    InventoryRow,
    LotScope,
    NoticeItem,
    Strength,
)
from storage.db import connect, init_db
from storage.repository import (
    append_revision,
    create_case,
    get_revision,
)

NOTICE = NoticeItem(
    name="Synthetic Test Medicine",
    strength=Strength(20.0, "mg"),
    form="tablet",
    holder=None,
    codes=(Code("GTIN", "05012345678906"),),
    lot_scope=LotScope.EXPLICIT_LIST,
    lots=("00123",),
    pack_size=28,
    evidence_span_ids=("S2",),
)

STOCK = InventoryRow(
    row_id="A",
    location="Demo Shelf",
    product_raw="Synthetic Test Medicine",
    strength=Strength(20.0, "mg"),
    form="tablet",
    manufacturer=None,
    holder=None,
    lot_raw="00123",
    expiry_raw="2028-01",
    pack_size=28,
    codes=(Code("GTIN", "05012345678906"),),
    quantity=4,
    unit="pack",
)


def test_case_survives_database_reopen(tmp_path):
    path = tmp_path / "recalldesk.db"

    conn = connect(path)
    init_db(conn)

    assert create_case(
        conn,
        "DEMO-001",
        "https://example.org/synthetic-notice",
        [NOTICE],
        [STOCK],
    ) == 1

    conn.close()

    reopened = connect(path)
    restored = get_revision(reopened, "DEMO-001")

    assert restored.revision == 1
    assert restored.notice_items == (NOTICE,)
    assert restored.stock_rows == (STOCK,)
    assert restored.stock_rows[0].lot_raw == "00123"
    assert restored.stock_rows[0].codes[0].value == "05012345678906"
    assert restored.source_verified is False

    reopened.close()


def test_new_revision_preserves_original(tmp_path):
    conn = connect(tmp_path / "history.db")
    init_db(conn)

    create_case(
        conn, "DEMO-002", "https://example.org/test",
        [NOTICE], [STOCK],
    )

    changed = replace(STOCK, lot_raw="00999")

    revision = append_revision(
        conn,
        "DEMO-002",
        stock_rows=[changed],
    )

    old = get_revision(conn, "DEMO-002", 1)
    latest = get_revision(conn, "DEMO-002")

    assert revision == 2
    assert old.stock_rows[0].lot_raw == "00123"
    assert latest.stock_rows[0].lot_raw == "00999"
    assert latest.stock_version == 2
    assert latest.notice_version == 1
    assert latest.source_verified is False
    assert latest.scope_reviewed is False

    conn.close()


def test_duplicate_stock_ids_are_rejected(tmp_path):
    conn = connect(tmp_path / "duplicates.db")
    init_db(conn)

    with pytest.raises(ValueError, match="Duplicate"):
        create_case(
            conn, "DEMO-003", "https://example.org/test",
            [NOTICE], [STOCK, STOCK],
        )

    conn.close()


def test_no_change_does_not_create_revision(tmp_path):
    conn = connect(tmp_path / "unchanged.db")
    init_db(conn)

    create_case(
        conn, "DEMO-004", "https://example.org/test",
        [NOTICE], [STOCK],
    )

    with pytest.raises(ValueError, match="No new evidence"):
        append_revision(conn, "DEMO-004")

    assert get_revision(conn, "DEMO-004").revision == 1
    conn.close()
