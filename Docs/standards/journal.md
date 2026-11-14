# The journal

**Status:** Living. Managed by the template (the `journal` module): a repository's copy must match, so do not edit it here;
propose a change to the template. How the journal is written, how a session file is named, who is named as its author, and how
its browsable index is made. The files themselves are the project's; [the journal directory's README](../journal/README.md) holds
the table of the older sessions.

**This project's additions** go in `journal-project.md` beside this file, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

## The commands

```bash
uv run python tools/render_journal_index.py            # render Docs/journal/INDEX.md (make journal does the same)
uv run python tools/render_journal_index.py --print    # the same text on standard output; writes nothing
uv run python tools/render_journal_index.py --authors  # who committed each session file; never fails the run
```

The page is **derived and not committed**: it is git-ignored, the docs check does not read it, and it cannot drift from the files.
Render it when you want to browse. The command is the interface; `make journal` is a convenience a repository may add (the
Makefile is the project's own file, so a repository that predates the target adds it by hand).

## What goes in it

- **The session's story, for a person.** Say what the developer is actually doing and the outcome they are driving
  towards, and why it matters now; then what moved towards it, and what the person decided. Someone who was not there
  should be able to follow it and care how it ends. Detail serves the story: the file, the finding or the commit
  belongs where it explains a turn in it, and an entry that is only a list of what was fixed is a log, not a journal.
- **Continuous, not retrospective.** At least one file per calendar day, and one per session. Batch at natural breakpoints: the
  test is whether someone reading it later could reconstruct *why*, not just *what*.
- **Beliefs that changed** are the most valuable content: what was believed, what contradicted it, what is true now.
- End an entry with a trailing arrow (`→`) linking the durable artifact it produced, when there is one.
- A session that crosses midnight closes its file with `**Continued in:**` and opens the next day's with `**Preceded by:**`. The
  split is never retroactive: entries are not moved between files. Two sessions on one day carry `**Ran in parallel with:**`.
- The journal is history: nothing in it is rewritten to match what is true now. A later file corrects an earlier one.
- **Two pull requests open at once from one session** both append to its file, and the second to merge conflicts.
  Stack the second on the first's branch, and say in its description that the first merges first. Work that must merge
  *before* a long-running branch (a template update, a fix the branch needs) does not stack on it: it goes off the
  default branch, and the long branch takes it by merging the default branch in, keeping both sides' journal entries
  and rows.

## A session file

Two name forms are session files, and every check that finds them recognises both:

| Form | Name | Author | Index |
| --- | --- | --- | --- |
| New | `YYYY-MM/YYYY-MM-DD-<login>-HHMM.md`: in the **month folder** of its day, the author's GitHub login (1 to 39 letters, digits or single hyphens), and the session's start in **UTC** | Named in each entry, checked against the roster | None: the directory listing is the index |
| Old | `YYYY-MM-DD-session-NN.md`, at the top of the journal directory | The owner | A row in the table in the journal README |

Use the new form for a new file, under its month folder (`Docs/journal/2026-11/` for a file dated in November 2026; make the
folder when the month starts). The old form stays valid at the top and is never renamed or moved, so no link moves. The two
cannot be confused: the old ends `-session-` and two digits, the new a hyphen and four. A `journal-index` finding: a file that
starts with a date and is neither form, a time that is not a time (`2460`), a day that is not a day, a new-form file outside its
month folder (at the top, or under another month), an old-form file inside one, anything else inside one, a month folder that
is not a month (`2026-13`), or a folder nested below a month folder. `INDEX.md` and the README stay at the top.

A link across a month is an ordinary relative link: `**Preceded by:**` in `2026-11/2026-11-01-ada-0100.md` names
`../2026-10/2026-10-31-ada-2300.md`, or an old-form file as `../2026-10-28-session-01.md`.

```markdown
# Session, 2026-10-27

**Status:** Living (append-only within the session).
**Summary:** One line, at most 200 characters: what this session decided or found.
**Preceded by:** a link to the previous file.   <- optional; **Ran in parallel with:** likewise

### A heading
**By:** @login[, @login ...] · **Agent:** the tool and model, or none
**Said by:** @login[, @login ...]                <- optional; the line directly after the By line
**Board:** [`<row id>`](../../plan/board/<row id>.md)   <- optional; when the entry is about a board row

Prose. A quote is tagged at the start of its line: @login: "what was said".
```

- **`Summary:`** is a header line, before the first `###`. It is the link text on the rendered page.
- An **entry** is a `###` section. Its first non-blank line is the `By:` line; `·` (U+00B7) separates `By` from `Agent`. `Agent:`
  is free text and may be `none`; it is never read beyond being present. **An agent is a tool, not a person**: it never appears in
  `By:` or `Said by:`.
- An entry about a board row may name it in a **`Board:`** line in its header (after `By:` and `Said by:`, before
  the first blank line), as a design does: the row's id as the link's text. The `row-ref` check reads it there, and
  the board page lists the entry under the row.
- A pairing session lists both people in `By:`. Several people may write in one file only by editing an entry they author.
- `@login:` at the start of a line tags a quote; write a doc tag such as `@param:` inside code or not at the start of a line.

## The roster

`framework.toml` may have a `[[people]]` table for each person who may be named:

```toml
[[people]]
login = "octocat"
name = "The Octocat"
role = "owner"                 # "owner" or "contributor"; the roster needs at least one owner, and may have several
emails = ["octocat@example.org"]   # the addresses this person commits with, each on the roster once; none: cannot sign a commit
```

**`init new` seeds the owner's row** when its answers carry `owner.login` (the prompt asks for it after the email;
an empty reply gives no login and no roster): the row above, with the owner's name, `role = "owner"` and the owner's
email, appended to the `framework.toml` it creates. A `framework.toml` already in the target is kept as it is, and the
run says no roster was seeded. Everyone else, and a second address, is added by hand.

A repository with **no roster is not checked for authorship**, and nothing else changes for it. With one, the docs check's
`journal-author` finding names a file whose login, entry authors, `Said by:` logins or `@login:` quote tags are not on it, a
file with no usable `Summary:`, an entry without its `By:` and `Agent:` line, or a `##` heading (an entry is a `###`
heading, and what follows a `##` one would be checked by nothing). Logins compare ignoring case, as GitHub does.

The roster also decides **who may commit**. The `commit-msg` hook accepts a `Signed-off-by` from the owner in `project.json`
or from a person on the roster with their `name` and one of their `emails`; a person with no address cannot sign. So adding a
row with an address lets that person commit, and anyone on the roster may merge that row: it is where a review is most worth
asking for. The rules are in [definition-of-done.md](definition-of-done.md) (*Identity* and *Who merges and who decides*).

Two limits are stated, not hidden. The roster is **evidence, not proof**: a squash merge or a rebase rewrites a commit's author,
and nothing proves an agent wrote what its entry says. And a decision a gate reserves for a person is judged in review, not by a
check. `--authors` compares each file with the commit that added it and prints a note where they differ; it reads git history, so
it says it skipped on a shallow clone, a repository with no commits, when git is absent, or when it cannot read the
configuration or the journal directory, and exits 0 each time. A file renamed later is attributed to
the commit that gave it its current name, because git sees a rename as an add of the new name.

## Two sessions that start in the same minute

Two sessions of one login that start in the same minute choose one name, and git reports an add/add conflict when the second
arrives. That is loud and cheap to fix (rename one by a minute), which is why the name does not carry a random part.
