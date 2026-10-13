# RecallDesk

Checks a medicine recall notice against pharmacy stock and sorts each stock
row into a match state for a pharmacist to review.

Team Redline Agents, AMD Developer Hackathon ACT III, Health and Wellbeing track.

All stock data in this repo is synthetic.

## Setup

Requires Python 3.11.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
pre-commit install              # optional, needs pre-commit installed
cp .env.example .env           # then fill in the AMD_* values
```

## Run

From the repo root:

```bash
python -m streamlit run app/main.py
```

Use `python -m streamlit` rather than `streamlit` so the repo root is on the
import path and imports like `from contracts import ...` resolve.

## Layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `contracts.py` | Both | Shared dataclasses, frozen after Oct 14 |
| `config.py` | Dev 1 | Env settings |
| `ingestion/` | Dev 1 | CSV and notice text loading |
| `extraction/` | Dev 1 | Model adapter, prompts, validation |
| `matching/` | Dev 2 | Match classification |
| `storage/` | Dev 2 | SQLite |
| `export/` | Dev 2 | PDF export |
| `app/` | Both | Streamlit UI |
| `fixtures/` | Dev 1 | Notices and synthetic stock |
| `tests/` | Dev 2 | Tests |
