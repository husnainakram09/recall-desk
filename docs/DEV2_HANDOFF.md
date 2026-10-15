# RecallDesk Dev 2 handoff

Dev 2 covers matching, versioned SQLite storage, review decisions, the Review
page, the Export page, and PDF evidence reports. The frozen `contracts.py`
remains unchanged. Dev 1 owns ingestion, extraction, fixtures, configuration,
the theme, and `app/main.py`; Dev 3 responsibilities are unchanged.

## Lead integration

The branch deliberately leaves the lead-owned entry point unchanged. Its
Review and Export routes are still placeholders until the lead applies the
provided patch. From the repository root, review and apply:

```bash
git apply --check docs/dev2-main-integration.patch
git apply docs/dev2-main-integration.patch
python -m streamlit run app/main.py
```

The patch imports `app.pages.review` and `app.pages.export`, calls their
`render()` functions for the existing page choices, and removes the Dev 2
placeholder. It does not change Import Stock or Notice behavior. If the lead
has already changed `app/main.py`, make those same two routing changes manually
after reviewing the current file; do not force an outdated patch.

Without touching the lead entry point, Dev 2 pages can be inspected with:

```bash
python -m streamlit run scripts/dev2_preview.py
```

Run both commands from the repository root with the project's environment
active. Using `python -m streamlit` keeps the root on the import path. The
preview offers Review/Export and a simulated role selector; it does not seed
fixtures or offer the lead-owned import/extraction steps. Existing saved cases
in the same local database can be reopened there.

## Normal saved-case flow

1. In the integrated app, import synthetic stock on **Import Stock** and
   prepare the notice draft on **Notice** using the existing Dev 1 flow.
2. Open **Review**. Enter the notice source URL and, only after the demonstration
   checks, select the self-attested source and affected-scope checkboxes. Save
   the session as a new case. The database snapshots the notice items and stock
   rows, then stores one finding per stock-row/notice-item pair.
3. Select a stock record and notice product. Inspect inventory, matched/missing/
   conflicting fields, the next evidence question, and available source excerpts.
   A saved case with either review checkbox unset stores `CHECK_INCOMPLETE`
   findings and blocks simulated review decisions.
4. Choose the simulated **Pharmacist** role. Enter a demonstration reviewer
   label and note, then record the action appropriate to that finding. This
   records a review event, not a clinical approval or instruction to handle stock.
5. Open **Export**, select the saved case, click **Prepare saved-case PDF**, and
   use **Download evidence PDF**. Export reads one consistent snapshot of saved evidence,
   stored findings, and review history; unsaved UI changes are not report evidence.
   Prepared downloads are not cached across page reruns: prepare again to report
   the current revision. A report can document incomplete checks or pending review
   decisions. Its availability never means a case is approved.

The state-specific actions are acknowledge candidate, request additional
evidence, escalate conflicting identifiers, and record a non-match for this
notice. `CHECK_INCOMPLETE` permits no decision. A non-match never establishes
safety or checks stock against every possible recall.

## Restart and corrections

The database is `.recalldesk_demo.db` relative to the working directory. It is
ignored by Git. Start from the repository root after a restart to reopen the
same cases. Select a saved case and **Open selected case** on Review; Export
lists saved cases independently. SQLite evidence snapshots, stored findings,
and review history survive a process/browser restart. Unsaved inventory,
extraction results, and the session's original notice text do not.

**Preview corrected finding** is transient. **Save correction as new revision**
changes the selected stock lot in a new snapshot and stores new findings in one
transaction. Prior snapshots and decisions remain in history. New evidence
resets source/scope check flags; the resulting findings are `CHECK_INCOMPLETE`
until fresh source/scope review. Old decisions are marked historical/stale by
comparison with the latest case revision and never transfer to the new revision.
An outdated expected revision is rejected rather than silently overwriting
newer evidence.

After a saved correction, manually recheck the original notice source and
affected product/lot scope, select the two new **I rechecked...** checkboxes, and
click **Record source and scope review for saved revision**. Each form is bound
to its displayed case/revision. The `rereview_case()` repository operation
appends another evidence revision and stores its findings atomically; it retains
the prior revisions and historical decisions. Fresh
decisions must be recorded for this latest reviewed evidence. Do not edit SQLite
flags directly or reuse a prior decision as new approval. Notice draft edits in
the unsaved session do not mutate a previously saved case; the caller must
explicitly save new evidence/revisions. The case's source URL is case-level
metadata and cannot be changed through the revision API.

## Security and evidence limits

- The role dropdown and reviewer label are simulation inputs. There is no
  authenticated pharmacist identity, credential verification, login, or
  clinical authorization. Application policy and SQLite insert validation
  restrict simulated decisions to reviewed, current evidence and the expected
  action for that state; they do not provide a security boundary against a
  person who controls the database or process.
- Repository functions append evidence revisions and decision history. The
  SQLite file is not cryptographically signed or tamper-proof. Triggers block
  ordinary UPDATE/DELETE statements, but a database owner can remove those
  guards or replace the file. There is no encrypted database, separate
  multi-user authorization, or retention policy in this demonstration.
- Source/scope flags are self-attested. A recorded URL is text metadata, not
  proof that a source was fetched, authentic, current, or independently verified.
  The database stores structured notice items, stock snapshots, span IDs, and
  review events. It does not persist the original notice file, verbatim source
  text, extraction call metadata, or span-to-page evidence mapping. A source
  excerpt can be shown only while its matching source snapshot remains in the
  session. That snapshot must match both the case and notice version; edits must
  not cause an old excerpt to be shown beside newer notice evidence. Reopened
  cases must be checked against the original source again.
- PDF reports identify saved evidence versions and decision history. They are
  synthetic demonstration records, not clinical clearances, signed approvals,
  regulatory records, or proof of actual stock action. Missing stored findings
  block generation; unresolved findings/decisions remain visible as pending.
  The built-in PDF font currently supports WinAnsi/Windows-1252 text. Text with
  unsupported Unicode (for example many non-Latin scripts or emoji) blocks
  export with a clear message instead of silently substituting broken glyphs.
  Stock and notice evidence is retained in SQLite; resolve font support before
  exporting such a case rather than changing evidence solely to get a download.
- The `approvals` table remains legacy schema. Current UI/report code uses
  `review_decisions`; it does not read legacy approval records as authoritative
  approval. Do not present a legacy row or a successful download as approval.
- Matching is deliberately conservative. It keeps identifiers as strings,
  preserves leading zeros, keeps manufacturer/holder roles separate, and does
  not guess ambiguous lot ranges. This checks the supplied notice items only.
  **No match in checked sources does not establish safety.**

## Verification before handoff

Verified on 15 October 2026 against the existing project environment:

- Ruff passed across Dev 2 pages, matching, storage, export, all tests, and the
  standalone preview. Full test suite: **113 passed**.
- Whitespace checks passed and the exact lead routing patch passed
  `git apply --check` against the unchanged current entry point.
- All four pages of the final synthetic sample PDF were rendered and visually
  inspected. Identifiers retain leading zeros; stock records stay together;
  evidence values, unresolved questions, current/pending reviews, page numbers,
  and limitations are legible. Automated stress checks also cover many rows,
  long identifiers, literal markup, unsupported characters, and concurrent
  revisions from a second SQLite connection.
- Streamlit AppTest verifies empty Export, saved evidence instead of unsaved
  session inputs, safe filename/MIME/payload, selection changes removing a
  prepared download, missing findings blocking export, and unreviewed status.
- Live browser smoke used a separate synthetic database in the workspace copy:
  empty Review, reopening saved evidence with no session source text, rows C/D,
  Technician restriction, Pharmacist conflict decision persistence, correction
  to a new incomplete revision, historical decisions, and fresh re-review.
  Export downloaded a revision-4 PDF with incomplete checks and stale history;
  its bytes/text were verified. Selecting another case cleared the download;
  missing saved findings blocked generation.

The full lead-owned import/extraction workflow and live AMD call were not
executed in this continuation. Those remain part of the coordinated integrated
team demo after the lead reviews/applies the routing patch.

Required checks from the repository root:

```bash
python -m ruff check app/pages matching storage export tests scripts/dev2_preview.py
python -m pytest tests -q
git diff --check
git apply --check docs/dev2-main-integration.patch
```

Browser smoke should cover empty Review/Export, opening a saved case after a
restart, rows C (missing lot) and D (conflicting identifiers), Technician versus
simulated Pharmacist decision controls, pending/incomplete review reporting,
and a saved correction that makes previous decisions stale. Generate and
download a saved-case PDF, inspect its rendered pages and source/version/row/
decision details, and verify that unsaved UI evidence is absent. Use an isolated
synthetic database for smoke checks and keep fixtures out of the product entry
point. The five full integrated demo passes still belong to the coordinated
team freeze check after the lead applies the routing patch.

## Branch and delivery

Keep implementation commits on `dev2/matching`; do not commit or push to `main`.
The prior pushed Dev 2 commit is `84c8393`. The verified continuation is
committed and pushed to this branch from a workspace copy; check Git history
for the final delivery SHA. Automatic approval review denied write access to
the resolved original checkout, so that checkout still has its original two
untracked report files. No original checkout changes or database writes were
made by this continuation. Main, contracts, Dev 1 source files, and Dev 3 work
were left unchanged. Generated smoke databases and rendered assets are not
committed.

To synchronize the original checkout, first inspect its status. Continue only
if it is still on `dev2/matching`, has no tracked changes, and its only untracked
files are the two original report files. Move those files to a backup outside
that checkout, then fetch and fast-forward:

```bash
cd ~/Projects/AMD_Hackathon/recall-desk
git status -sb
git branch --show-current
task_backup="../recall-desk-dev2-local-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$task_backup/export" "$task_backup/tests"
mv -i export/report.py "$task_backup/export/report.py"
mv -i tests/test_report.py "$task_backup/tests/test_report.py"
git fetch origin
git pull --ff-only origin dev2/matching
git status -sb
```

The move preserves the local drafts and removes the untracked-file collisions
that would otherwise block pulling their tracked final versions. Keep the
backup until those drafts have been compared with the delivered files. If the
branch/status differs or the pull reports divergence, reconcile that work first.
Do not use reset, clean, or force-push. Rerun the verification checks in the
original checkout. The lead routing patch remains a separate coordinated step.
