# Failure modes: the framework's ledger

**Status:** Living. Managed by the template: a repository's copy must match, so do not edit it here; propose a change to the
template.

**This project's additions** go in [failure-modes-project.md](failure-modes-project.md) beside this file: an extension
adds rules and never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a
reason that names the rule.

**This is the ledger of how AI-assisted work goes wrong**, not the work. It was drawn from the failure ledgers of three real
repositories: each entry is a defect in process that one of them could prove from its own history, written as **Trigger,
Do, Because** so it is usable at the moment it applies. The *Because* line says what happened. It works by being read: the
entry file tells every session to load it before starting, so retrieval is the enforcement. Where the repository has a check
that holds a class, the entry ends with a **Mechanised by** line naming it, and a test compares those names with the
docs check's.

Entries are append-only. Never rewrite one; add a new entry that supersedes it and say which. Cross-references say
"framework 5" or "project P-1", because both ledgers are numbered.

## If you notice...

| If you notice | Read |
| --- | --- |
| You are about to write "done", "passing", "fixed in `<hash>`" or a number | 1 |
| A command chain with a pipe after the command that decides | 2 |
| A script with backslashes or quotes going through a shell heredoc; a file written empty | 3, 4 |
| Another session has touched the same living documents; a pull request or branch you did not create | 5, 6 |
| An idea was just said; a board row is about to be built; the board grows faster than it lands | 7, 8 |
| You are about to write "follow-up" or "later" next to a bug | 9 |
| A document, plan or handoff header looks current; you are about to port from a description | 10 |
| A check, probe or test returned nothing, or asserts only the kind of answer | 11, 12, 13 |
| You are about to say something does not work, or an unrelated step failed | 14, 15 |
| A push is finished; a value passes on your machine; a hash of a file or of floats | 16, 17 |
| Work is fast and a discipline is unchecked; the same rule is about to go in a second file | 18, 19 |
| A new word, a late addition to a reviewed document, a default from another repository | 20, 21, 22 |
| An automated review; a stacked pull request; a wide diff; a link; a manifest or an unwired file | 23, 24, 25, 26, 27 |
| A test or tool that ships to every repository reads a file the project owns; it has only run in a repository nobody edited | 28 |
| You are adding an override, a skip, an allow-list line or an exempt folder | 29 |
| A guide, migration or design says it works, or that something cannot fail, and you have run only the default case | 30 |
| A second path produces what another already does | 31 |
| A status word sits beside a link | 32 |

## The ledger

### 1 · A claim made before the evidence exists

**Trigger:** Writing "CI green", "tests pass", "fixed in `<hash>`" or a number (a test count, a frame time, a figure quoted
from another document) into a reply, a pull request body, a review thread or a document.
**Do:** Run the thing, read the result, then write the sentence. Quote a number with the commit and the machine it came
from, never carry one forward, and when you cite a figure from another document re-read the source line and check the label
means the same thing. Before a reply names a commit, confirm the commit exists (`git log -1` differs from the previous
head), and join the steps with `&&` under `set -o pipefail` so a failed step cannot be followed by the reply that claims it.
A box ticked at open is unticked until read.
**Because:** A pull request went out with its CI box ticked while CI was pending. Five review replies said "Fixed in
`<hash>`" naming the previous head, because the patch script that was meant to make the commit had failed on its first
anchor. Each was true a few minutes later, which is not the same as true. A handoff quoted a test count that was wrong by
more than a thousand a month later while its rules still held, and a figure was quoted under another quantity's label.

### 2 · A gate whose failure a pipe swallowed

**Trigger:** A command chain with `| tail`, `| head` or `| grep` after the command that decides, or any chain that
continues to a commit or push after it.
**Do:** Capture the exit code (`cmd > log; rc=$?`, or `set -o pipefail`) and test it before anything that commits or
pushes. A gate is only a gate if its failure stops the next command.
**Because:** A first commit went out with two failing tests because the test runner's exit code disappeared behind a
`tail` and the chain went on to `git push`. The same shape merged a milestone on a failing gate in another repository.

### 3 · A script carried through a shell heredoc

**Trigger:** In an agent's shell tool, writing a script or a file's contents that contains backslashes (`\n` in strings,
regular expressions, Windows paths) or apostrophes inside a heredoc; or a heredoc that fails with `unexpected EOF`, a
`SyntaxWarning: invalid escape sequence`, or a `\n` that arrives as a real newline.
**Do:** Write the script to a file with the editor's write tool and run the file; do not pipe a script through a heredoc
however it is quoted, and do not re-escape and retry. Have every patch script assert that each anchor matches exactly once.
After any failed script, run `git status` before the next step and read the diff before quoting a commit as the fix.
**Because:** It happened more than a dozen times across three repositories: a test file left syntactically broken, a patch
that silently skipped its anchor so the following commands ran against the unpatched tree, and a tree left half-patched.

### 4 · A write that fails after it has already emptied the file

**Trigger:** A script that writes a file with an argument you have not run before (an encoding, a line-ending mode, a
flag), or a write that raised an exception.
**Do:** Write the new content to a temporary path first and move it over, or run the script on a copy; after any failed
write, `git status` before the next step. Many file APIs truncate a file when it is opened for writing, before the
other arguments are validated, so a bad value raises with the file already empty.
**Because:** A write with a literal backslash-n as its line-ending argument emptied a job's test file and later another test
file; each came back from version control and the lost edit was redone.

### 5 · Two sessions writing the same living document

**Trigger:** More than one session is working the same repository on the same day, or another session has a pull request
open or merged today that touches the handoff, the board, the journal or an instruction file.
**Do:** Expect the conflict in the living documents, not in the code. Merge the default branch before opening or updating
your pull request, resolve by hand, and deduplicate: the same event recorded twice is one row. Re-run the docs check.
**Because:** In one repository two sessions that never touched the same code collided in `docs/`: both created the same
numbered journal file, and both logged and cleared the same decisions. In another, two sessions rewrote the same handoff
line and added the same row on the same day. A living document is a shared mutable, and documents that are append-only by
convention collide hardest.

### 6 · Not your branch, and a positive that proves only co-location

**Trigger:** Being pointed at a pull request, branch, worktree or process you did not create in this session ("85 has open
review comments"); about to delete a directory, worktree or branch; or a tool that tells you something is yours.
**Do:** Ask whose it is before reading the diff, let alone writing. Treat a check as strong evidence of *not yours* and weak
evidence of *yours*: "I am next to it" is not "I own it". Before suggesting or running anything that deletes a directory,
check whether a live session's working directory is inside it, your own included, and hand cleanup over at the end of the
work, not in the middle of a plan.
**Because:** In a repository where every pull request carries the owner's identity by policy, a pull request number reads
like a work order, and a session started work on another session's branch. A tool built to prevent exactly that reported
"yours" for a branch checked out in the shared checkout, because it measured co-location and reported ownership. Another
session died mid-conversation when the directory it was working in was removed from under it.

### 7 · A mentioned idea is not a work order, and a board row is not a lock

**Trigger:** The owner names something that will be needed; a reply to a menu of options; "let's move on" or "what next"; a
board row with a cost and a verdict that is about to be built.
**Do:** Put the idea in the board's Icebox in the same session, with a cost, a reason it is not built now and a verdict, and
say where it landed. Build immediately only on an explicit go, when it blocks work in flight, or when it is smaller than the
conversation about it; ask "pull it forward now?" in those words before building an Icebox row. Follow the design chain in
the entry file; a verdict on an idea is not a lock on its shape, and a new tool is a significant increment whatever its
size: spec and plan first. When corrected, do not answer with a spec full of recommendations (that is still deciding ahead
of the owner): write down the conversation's input and stop, and hold code already written uncommitted and named, for the
owner to keep or drop.
**Because:** Four modules were built off one sentence listing things the project would need. A new editor was built from a
board row's "yes" with no design, and the owner asked what had gone wrong. A write-up, with a 300-line generator and no spec
or plan, was built because a reply to a menu of options was read as a go.

### 8 · Idea velocity outrunning landing velocity

**Trigger:** A day that adds more board rows than it strikes through; "next" unchanged for two sessions.
**Do:** Say it out loud, then land the next increment before the next idea. The board exists so ideas keep, not so they
queue forever.
**Because:** One day added nine Icebox rows and three design-first items while the standards pass stayed "next" from the
previous morning.

### 9 · A deferred defect with no home

**Trigger:** Writing "follow-up", "later" or "iceboxed" next to a bug in a pull request, a review reply or a board row; or
reading a review that posted after its pull request merged.
**Do:** Open a tracker issue before the pull request merges (or before the session ends when the finding came late) and put
its number where the deferral was written. The board tracks features, spikes and gates; defects are issues.
**Because:** Three pull requests each ended with a paragraph of deferred review findings, one set from a review that posted
five minutes after the merge; the only record was two long Icebox rows on a board that scrolls, and nothing would have
reopened them.

### 10 · A document, plan or belief that reads as live or true when it is not

**Trigger:** Reading a document whose header says "in progress"; porting, summarising or planning from a roadmap or a
README's description of what code does; writing a definition or section next to existing ones; or updating a handoff's
*Last updated* line and its sit rep.
**Do:** Trust the `**Status:**` line, not the progress text; change a plan's status in the same pull request that lands or
abandons it. Read the source, the include graph or the log, and correct the document in the same change. Read the
neighbours of anything you add and fix what the current decisions have invalidated. When the state changes, re-read the
handoff from the top and fix every pointer: a reader who sees "the next step is S2" after S4 merged is sent to obsolete work.
**Because:** Seven plans from months earlier sat beside live documents, six describing work finished long ago and one a
component that had been deleted. A roadmap said a library shipped three variants when its source included one. A glossary
called a unit "device-resident" days after a decision moved it to the host. A handoff said nothing was in flight while its
reading order still carried a pointer that had last been true several increments earlier, rewritten around five times
without being read.
**Mechanised by:** `status`, `single-status`, `handoff` and `journal-day` hold the header, the handoff's date and its length; whether the
content is still true is judgment.

### 11 · A probe or check that can only return the boring answer

**Trigger:** A probe, grep, mutation run or checker returns "nothing": no matches, no failures, no difference; a check that
skips regions (fenced code, excluded folders, a `try` around a whole loop); or a feature flag that is always false.
**Do:** Before believing it, make the same instrument produce the other answer: run the unmutated control, print a marker,
search the bare identifier and read the hits, break the rule on purpose and require a failure. Make a skip that swallows
more than intended a finding, and test the edges (an unclosed fence, a link above the root, a byte-order mark).
**Because:** A project's probes died silently seven different ways, ten mutants in a row matching the unmutated control
because the test setup put the repository's own packages ahead of the installed ones. A docs checker dropped everything
after an unclosed fence, so links and status lines after a typo went unchecked and the file looked green.
**Mechanised by:** `corpus` (a scan of zero files is a finding) and `fences` (an unclosed fence is a finding); the edges are the docs
check's own tests.

### 12 · A guard tested for a weaker property than it claims

**Trigger:** Adding a defensive guard (a zero check, a finiteness check, a fallback return) and testing it with
`assert isfinite(out)`, `assert out.shape == ...` or `assert out is not None`: a property of the kind of answer, not the
answer.
**Do:** Assert the value the guard is supposed to produce, one assertion per case. Then mutate the guard to the other
case's return and watch the test fail; a guard whose test survives swapping its branches is not guarded. A positive answer
must be tested from the side that is trusted, not only from the side that looks dangerous.
**Because:** A guard that returned zeros for a non-finite scale had a finite equal-endpoints case folded into the same
branch in review, so a valid input became black. The test asserted only that the output was finite; zeros are finite, so the
regression passed the whole suite and an automated reviewer found it.

### 13 · A control that cannot distinguish the alternatives

**Trigger:** Diagnosing a failure that has a plausible first explanation, and running a control or an A/B check to confirm
it.
**Do:** Vary what actually differs between the failing and the working case, not only your favoured hypothesis. A control
that varies only the hypothesis you already hold is decoration: ask what result would have changed your mind, and make sure
the experiment can produce it.
**Because:** A control varied the wrong parameter and "confirmed" a cause that was not the cause; the real difference sat in
the one thing the control held fixed.

### 14 · A negative result inherits its implementation's assumptions

**Trigger:** About to report that something does not work, or is dead, or is too slow.
**Do:** State which implementation produced the result and what it assumed. Ask whether a different implementation of the
same idea would change the answer.
**Because:** A measurement showed one approach at 4.3 times the budget and the handoff said it killed the whole family of
approaches; the measurement had assumed one operation per part, and the same design done the other way was 1.46 times. The
result was real and the inference was not.

### 15 · Something failed that had no business failing

**Trigger:** An unrelated step breaks, especially a sanity check or a round trip.
**Do:** Write down the failure and do not retry, skip or route around it until you can explain it; chase it immediately.
**Because:** Reading an exporter's output back through a second tool failed, on a format the second tool supports. Chasing
that exposed the real defect, which the deliberate testing had missed. The round trip that was meant to be a formality caught
the error.

### 16 · The local environment is not CI's

**Trigger:** Pushing and reporting it done; a test module that imports something outside the installed packages; a gate that
passes locally on a machine with every optional dependency installed.
**Do:** Read the run's conclusion before calling a push finished (on GitHub: `gh pr checks --watch`), and ask the owner to make the
default branch require the CI checks so a red run blocks a merge instead of waiting to be noticed. Run new test modules the
way CI invokes them, and make the local gate run in CI's environment, not only in yours.
**Because:** CI on the default branch failed on every push for three days across three sessions, including every commit
whose message said the gate was green, because two modules imported an optional package CI did not have and a collection
error stops the whole run. A root-relative import passed under one way of invoking the test runner and was a collection error
under the way CI invokes it, on both CI legs.

### 17 · A value that is not portable

**Trigger:** Recording the hash of a text file as an identity, or comparing one across machines; or pinning the hash of
computed floating-point output (a matrix, a packed buffer, a generated image).
**Do:** Hash text with line endings normalised and pin the files a tool reads to `eol=lf`; hash images and binaries as bytes.
Never pin the hash of computed floats: recompute the value by the formula in the test, exactly on one machine or with a
stated tolerance across them. A hash that passes locally and fails on the other platform is this, not a stale cache.
**Because:** Twenty-nine inputs "changed since the cook" on a Windows runner without a byte of content changing, because
checkout had rewritten the line endings. Three tests pinned the SHA-256 of a generated image taken on the owner's machine and
failed on CI with different bytes, which depend on the numeric library, the CPU and the compiler.

### 18 · An unmechanised discipline, under pressure

**Trigger:** Work is going fast and well.
**Do:** That is exactly when the unchecked disciplines lapse. Compare the newest journal file's date and the board's
*Updated* line with the work since; if either is behind, the others have probably slipped too. Mechanise the class whenever a
check can hold it, and name the check in the entry.
**Because:** Six commits landed before the journal existed. "It slipped exactly where the work got fast." The mechanised
documentation kept up perfectly, because it is checked; the owner asking "are we keeping up on journalling?" was the only
detector.
**Mechanised by:** `journal-index` and `journal-day` hold the journal; the board's *Updated* line is judgment.

### 19 · A rule written in many places drifts

**Trigger:** About to write a standing rule (a convention, a command, a prohibition) into an instruction file, and noticing
that another file already says something about the same subject.
**Do:** Put the rule in one topic file and make everything else link to it. An instruction file may state the imperative and
link; it must not restate the rationale, which is the part that drifts. Never add a second prose copy "for the other tool":
the entry file is tool-neutral and every agent reads it.
**Because:** Making one rule durable meant hand-writing it into three instruction files; a fourth copy appeared in the pull
request meant to single-source it, and a long tool-specific copy had drifted far enough to document a runtime that had been
deleted weeks earlier.
**Mechanised by:** `nested-instructions` holds one kind of second copy, an instruction file below the root; the rest is judgment.

### 20 · A new word that never reaches the glossary

**Trigger:** Writing a name for a concept the glossary does not hold: a module, a type, an enum value, a level, a CLI verb,
a document type.
**Do:** Add its glossary row in the same change and before the code or document that uses it, and give every design, spec
and plan a *Terms introduced* section (or "None"). A word used in three documents and a package without a row is a
word whose meaning only its author holds, and a concept with two names is retrieved by neither.
**Because:** A design, a spec and a build used a dozen new terms with no glossary row until the owner asked mid-build, and
one of the words already meant something else in a sibling project.
**Mechanised by:** `terms` (the section, and each listed term's row), `glossary-row` and `vocabulary` (a retired term
is not used as current). A new name in code that no document lists is judgment.

### 21 · An author's additions that skip the review

**Trigger:** Adding a section to a reviewed document after its review pass, at the author's own request.
**Do:** Run the pass again over the additions before calling the document done; additions arrive with the most conviction
and the least review.
**Because:** Sections added after the first editorial pass carried a promise the proposed schedule did not keep, a ledger the
repository did not have, and sample numbers that read as measurements. The second pass caught all three.

### 22 · A default assumed from another repository

**Trigger:** Creating a pull request, naming a branch, or using a path convention, a CI leg count or a "standard" practice
from the last repository worked in, or from how such things are usually done.
**Do:** Read this repository's own value (`git symbolic-ref refs/remotes/origin/HEAD`, or on GitHub `gh repo view --json
defaultBranchRef` where that is unset) and write it into the procedure that needs it. Check a borrowed convention against the
project's own measurements.
**Because:** Two pull request creations failed because the repository's default branch was not the one carried over from the
last repository. A convention that is "normally followed" overrode a number the project had measured.

### 23 · Review findings the review body hides

**Trigger:** Assessing an automated review that shows some number of threads.
**Do:** Fetch the review body too (on GitHub: `gh api repos/<owner>/<repo>/pulls/N/reviews --jq '.[].body'`) and, if the reviewer has a
"suppressed comments" section, read it; assess those with the threads.
**Because:** Two reviews carried four and five suppressed findings, none shown as threads; one exposed that an application
had been broken for months.

### 24 · A merged branch deleted under a stacked pull request

**Trigger:** Merging, or asking the owner to merge, a pull request with `--delete-branch` while another open pull request is
based on that branch.
**Do:** Retarget the stacked pull request first (on GitHub: `gh pr edit N --base <default-branch>`), then merge and delete.
**Because:** Deleting a branch after its pull request merged closed the one stacked on it, and a closed pull request whose
base is gone cannot be reopened or retargeted; the work was reopened under a new number.

### 25 · Files in the commit that the change never meant to touch

**Trigger:** About to run a formatter or a `--fix` over a directory in a tree that has files the change did not touch;
`git add -A`; or a status with a file whose name looks generated (`.coverage.*`, `*.pid*`, a temporary file).
**Do:** Name the files. Read the status before staging and stage paths, not `-A`, when the tree has run tests or tools since
the last commit. Add the pattern to `.gitignore` when one gets through. Do not reformat files the change did not touch.
**Because:** A formatter run on a package picked up five unrelated reformatted files that an automated reviewer listed as
"formatting cleanup"; an earlier run had rewritten 115. A coverage data file was committed and then deleted and recreated by
every later run until it was ignored.

### 26 · A link that resolves on the machine that wrote it

**Trigger:** A relative link whose spelling you typed from memory, or a path into a folder whose case you have not checked.
**Do:** Run the docs check, which compares each path component against the directory listing, so a link that resolves only
on a case-insensitive file system is a finding here as it is on a case-sensitive CI runner. Do not trust `exists()`; on
Windows `resolve()` returns the on-disk spelling, the very thing to compare against.
**Because:** A link to `archive/docs/` where the directory was `archive/Docs/` passed locally because Windows said the file
existed; the Linux runner would not have.
**Mechanised by:** `links`.

### 27 · Work that lands unwired, and a manifest nobody registered

**Trigger:** About to commit something no demo and no test reaches; or adding a job, a model, a module or a host: anything
with a registry beside it.
**Do:** Wire it, or leave it on a `wip/` branch. Prefer discovery to a hand-kept list; where the list exists, a test fails on
a member missing from it, and on an entry that matches nothing.
**Because:** A shared source file sat canonical and included by nothing for a whole increment, dead text nothing ever
compiled. A job carried a manifest for a day while the registry listed only the first job, so the registry could not find it.
**Mechanised by:** `orphan` holds the documents (one no chain of links reaches from the map is a finding); a
manifest has its own test.

### 28 · A managed test that assumes a project-owned file is unedited

**Trigger:** Writing or changing a test or tool that ships to every repository and reads a file the project owns (the glossary,
the handoff, `framework.toml`, the Makefile, the workflow); or "it passes in the repository the suite builds for itself".
**Do:** Build what the test needs from fixed text inside the test, or make the test payload-only (skipped once a
`project.json` exists) when it is about the seeds as shipped. Prove it on a repository that was made, edited as a project edits
it, and kept.
**Because:** Four managed tests failed on the template's own root the first time it was made from its payload, because they
read the glossary, the handoff and `framework.toml` as seeded; a fifth read the live module states and failed as soon as a
module was turned off. Every earlier run had been in a repository built by a test and never edited, so the suite had never
met the thing every real project is.

### 29 · An exemption wider than its reason

**Trigger:** Adding or reading an override, an allow-list entry, a skip or an exempt directory.
**Do:** Scope it to the one thing it excuses and name that thing. Add a test that an unlisted neighbour is still checked. A
generated counterpart inherits the exemption of its source and no more.
**Because:** One overridden document disabled a scan of all documents; an exemption for large files contradicted the standard
that promised every file is read; a standard library name hid a project package of the same name. In each, the exemption was
written for the case in front of the author and applied to its whole neighbourhood.

### 30 · A procedure or claim never run once, on a case that differs from the default

**Trigger:** A guide, a migration, a design's "cannot", or a release procedure about to be called verified.
**Do:** Run it once by hand on a case with a choice in it (a module off, an override, an earlier day, a removed file, the same
account twice), put that case in a test, and break the key step on purpose to see the test fail. Say what the guarantee is not.
**Because:** A release procedure failed at its second step, an update guide dropped a repository's choices, and a "cannot
collide" claim excluded the nearest case it should have tried. A later acceptance item described an adoption that the template
refuses; it was written for a path nobody had run. The project ledger holds three (P-2, P-3, P-4); this is the rule they share.

### 31 · A second path to the same state that ignores the configuration the first honours

**Trigger:** A second code path (a re-run, a render into a fresh folder, a regeneration, a filter, a link written beside a file
it was configured to find) that produces what another already produces.
**Do:** Read the configuration the first path reads, in the same order; the test runs both on a target with a non-default
choice.
**Because:** A planner that filtered shipped files by module and not by enabled adapter created files its own check rejected; a
render into an empty folder lost the repository's module choices and its first-run day; a generated page wrote beside the
configured directory and linked to a file name it had written as a literal.

### 32 · A status written beside a link goes stale

**Trigger:** Writing "(Proposed)", "(Accepted)" or a status column next to a link to a document that has its own status line, in
a map, an index, the board, the handoff or a README.
**Do:** Do not copy the status: link, and let the document carry it. Where a copy is wanted, the `status-copy` check holds it,
and a historical mention says "was".
**Because:** Eight times in pull requests 21 to 47 a copy was left behind when the owning document moved, and three ledger
entries (10, 19 and the project's P-1) already described the class, and it recurred. A status that was never moved in the
owning document (a merge that did not change its header) is judgment, not a check.
**Mechanised by:** `status-copy` holds the copy against the document's own status line, in three forms: after a link, before
one, and a table cell beside the row's one governed link.

## How to add an entry

When the process fails again, append the entry in the same pull request as the fix, to the project ledger (or propose it to
the template if any repository would repeat it): a trigger you would notice, the action it should cause, and the evidence.
Mechanise the class when a check can and name the check on a `**Mechanised by:**` line after the *Because*. Never rewrite an old entry; add a new one that
supersedes it.
