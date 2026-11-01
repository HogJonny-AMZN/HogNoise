# Journal

**Status:** Living. The append-only narrative of HogNoise: what happened, what was decided, and which beliefs changed.
Seeded on 2026-10-31.

## Rules

The rules, the two file-name forms, the authorship lines and the roster are in [the journal standard](../standards/journal.md).
In short: at least one file per calendar day and one per session; a new file is named `YYYY-MM-DD-<login>-HHMM.md`, lives in
the month folder of its day (`YYYY-MM/`, beside this file) and needs no row below; beliefs that changed are the most valuable content. To browse the newer sessions, render the page:
`uv run python tools/render_journal_index.py` (`make journal`), which writes a git-ignored `INDEX.md` beside this file.

## Index of the older sessions

The files named `YYYY-MM-DD-session-NN.md`; every one is a row here.

| Date | Session | What |
| --- | --- | --- |
| 2026-10-31 | [Session 01](2026-10-31-session-01.md) | A fresh public history; the repository adopts the template (ADR-001) |
