# The board's rows

**Status:** Living. One file per row of the board, named `YYYY-MM-DD-<slug>.md` (the day the row was written; the slug
lowercase letters, digits and single hyphens). The page a reader sees, [BOARD.md](../BOARD.md), is rendered from these files
by `make board` (`uv run python tools/render_board.py`) and is git-ignored: change the row, not the page.

A row file is a title line, then header lines, then prose:

```markdown
# The thing the row is about

**Section:** now            <- gate, now, next, blocked or icebox
**Owner:** @login           <- who holds it; `none` on a gate or an Icebox row
**State:** Started          <- one line; a done row starts with Landed (and names its pull request), Closed or Dropped
**Decider:** @login         <- a gate only: who closes it (anyone on the roster when absent)
**Cost:** 2 d               <- an Icebox row: a number or a range and a unit, then an explanation if you like
**Verdict:** Good           <- an Icebox row
**Raised:** [where](../../journal/README.md)   <- an Icebox row: a link to where the idea was said

The prose the row needs, with its links.
```

The `<-` notes are not part of a file, and the lines marked for a gate or an Icebox row are refused on any other row: a
`now` row carries `Section`, `Owner` and `State`, and may add `Cost`, `Raised` and `Was owned by`.

Before adding an Icebox row, search these files for the idea: two people must not start one piece of work. The docs check
holds every row to its section's lines (`Docs/standards/definition-of-done.md`, the `board` row of its table).
