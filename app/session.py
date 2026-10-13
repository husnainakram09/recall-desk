"""st.session_state keys shared between pages. Dev 2's pages read these."""

ROLE = "role"  # "Technician" | "Pharmacist", sidebar dropdown
INVENTORY = "inventory"  # list[InventoryRow], set by Import Stock
NOTICE_ITEMS = "notice_items"  # list[NoticeItem], saved drafts with a name

# Internal to the Notice page.
NOTICE_TEXT = "notice_text"  # ingestion.notice_reader.NoticeText
EXTRACTION = "extraction"  # extraction.validate.ExtractedNotice | None
CALL_META = "call_meta"  # extraction.token_factory.CallMeta | None
VALIDATION_ERRORS = "validation_errors"  # list[str] | None, after two failures
DRAFT = "notice_draft"  # list[NoticeItem]; name may be "" while incomplete
DRAFT_RUN = "notice_draft_run"  # bumps on each new draft so form keys reset
