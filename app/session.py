"""st.session_state keys shared between pages. Dev 2's pages read these."""

ROLE = "role"  # "Technician" | "Pharmacist", sidebar dropdown
INVENTORY = "inventory"  # list[InventoryRow], set by Import Stock
NOTICE_ITEMS = "notice_items"  # list[NoticeItem], saved drafts with a name
STOCK_SOURCE = "stock_source"  # fixture label when demo stock is loaded, else None
NOTICE_SOURCE = "notice_source"  # fixture meta dict when the MHRA fixture is loaded

# Internal to the Import Stock page.
STOCK_CSV_TEXT = "stock_csv_text"  # last CSV text loaded, for the preview
STOCK_UPLOAD_ID = "stock_upload_id"  # file_id of the last processed upload

# Review page.
REVIEW_MODE = "review_mode"  # "new" | "open"
REVIEW_MODE_NEXT = "review_mode_next"  # applied before the mode widget renders

# Internal to the Notice page.
NOTICE_TEXT = "notice_text"  # ingestion.notice_reader.NoticeText
EXTRACTION = "extraction"  # extraction.validate.ExtractedNotice | None
CALL_META = "call_meta"  # extraction.token_factory.CallMeta | None
VALIDATION_ERRORS = "validation_errors"  # list[str] | None, after two failures
FAILED_CALL = "failed_call"  # (CallMeta | None, message) of the last failed attempt
DRAFT = "notice_draft"  # list[NoticeItem]; name may be "" while incomplete
DRAFT_RUN = "notice_draft_run"  # bumps on each new draft so form keys reset
