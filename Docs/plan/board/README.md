# The board's rows

**Status:** Living. One file per row of the board, named `YYYY-MM-DD-<slug>.md` (the UTC day the row was written; the
slug lowercase letters, digits and single hyphens). The page a reader sees, [BOARD.md](../BOARD.md), is rendered from these files
by `make board` (`uv run python tools/render_board.py`) and is git-ignored: change the row, not the page.

A row file is a title line, then header lines, then prose:

```markdown
# The thing the row is about

**Section:** now            <- gate, now, next, blocked or icebox
**Owner:** @login           <- who holds it; `none` on a gate or an Icebox row
**State:** Started          <- one line; a done row starts with Landed (and names its pull request), Closed or Dropped
**Decider:** @login         <- a gate only: who closes it (anyone on the roster when absent)
**Cost:** 2 d               <- an Icebox row: a number or a range and a unit, then an explanation if you like;
                               `unsized: <reason>` when no one can size it yet; a Closed or Dropped row may leave it out
**Verdict:** Good           <- an Icebox row; any row but a gate may keep it
**Raised:** [where](../../journal/README.md)   <- an Icebox row: a link to where the idea was said
**Waits on:** [the row](<row file>.md)   <- next, blocked or icebox: the row whose landing would change this one's decision

The prose the row needs, with its links.
```

The `<-` notes are not part of a file. A line its section does not allow is refused: a `now` row carries `Section`,
`Owner` and `State`, and may add `Cost`, `Verdict`, `Raised` and `Was owned by`; `Decider` is a gate's alone; `Waits on`
is refused on `now` and on a gate.

**A row's id** is its file name without `.md`. Once the row is on the default branch the file is never renamed or
deleted (the `row-kept` check compares the tree with the base): its title may be reworded, its name may not. Before
then a rename is free, and is how two branches that chose the same day and slug are reconciled. Every design, spec
and plan names its row in a `**Board:**` header line, ``**Board:** [`<id>`](<path to this file>)``, or
`none (reason)`; the board page lists, under each row, the files that name it.

**Moving a row.** Pulling an Icebox idea forward edits its row file in place, never a second row on *Now*: `Section`
becomes `now`; `Owner` becomes the login that takes it (an Icebox row may say `none`, a *Now* row may not); `State` is
rewritten; a `Waits on` line is removed, because the wait has been decided; `Cost`, `Verdict` and `Raised` stay as
history. The same holds for a row moved to *Next* or *Blocked*, which keep a `Waits on` line that still applies. Work
lands from *Now*: a row whose state says `Landed` in *Next*, *Blocked* or the Icebox is a finding (`board-state`), and so
is a `Queued` row in *Now*.

**A wait on other work is a `Waits on` line**, not prose. The `waits-on` check fails when the row it links is done, so
the row is decided again; a wait written as prose is checked by nothing.

A row is work in this repository. Work in another repository goes on that repository's board, even when it was said here;
a row here names another repository only as the evidence for a change to this one, or links that repository's row when it
waits on it (`Docs/standards/workflow.md`, *Standing rules*).

Before adding an Icebox row, search these files for the idea: two people must not start one piece of work. The docs check
holds every row to its section's lines (`Docs/standards/definition-of-done.md`, the `board` row of its table).
