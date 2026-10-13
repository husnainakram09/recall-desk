"""Send one short text to the AMD endpoint and print the raw response and latency.

Usage, from the repo root:  python -m scripts.smoke_extract
"""

import json
import sys

from config import ConfigError
from extraction.prompts import build_user_message
from extraction.spans import split_spans
from extraction.token_factory import ExtractionError, TokenFactoryAdapter

# Synthetic test text, not a real recall notice.
SAMPLE_TEXT = """\
Test text, not a real notice.
Product: Example tablets 20 mg, packs of 28.
Affected batch: AB12C3.
"""


def main() -> int:
    try:
        adapter = TokenFactoryAdapter()
        parsed = adapter.extract(build_user_message(split_spans(SAMPLE_TEXT)))
    except (ConfigError, ExtractionError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    meta = adapter.last_call_meta
    print("Raw response:")
    print(json.dumps(adapter.last_raw_response, indent=2))
    print("\nParsed:")
    print(json.dumps(parsed, indent=2))
    print(f"\nRequest id: {meta.request_id}")
    print(f"Model:      {meta.model}")
    print(f"Latency:    {meta.latency_ms:.0f} ms ({meta.attempts} attempt(s))")
    print(f"Usage:      {meta.usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
