"""Load the demo fixtures from fixtures/. See fixtures/README.md."""

import json
from pathlib import Path

from ingestion.notice_reader import NoticeText, read_pasted

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
STOCK_CSV = FIXTURES_DIR / "stock_demo.csv"
NOTICE_TXT = FIXTURES_DIR / "notice_el25a17.txt"
NOTICE_META = FIXTURES_DIR / "notice_el25a17.meta.json"

STOCK_LABEL = "fixtures/stock_demo.csv"


def stock_csv_text() -> str:
    return STOCK_CSV.read_text(encoding="utf-8-sig")


def notice() -> tuple[NoticeText, dict]:
    meta = json.loads(NOTICE_META.read_text(encoding="utf-8"))
    return read_pasted(NOTICE_TXT.read_text(encoding="utf-8")), meta
