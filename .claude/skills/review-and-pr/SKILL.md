---
name: review-and-pr
description: Open a pull request the way this repository expects, and assess an automated review on one (fix valid findings, refute wrong ones with evidence, reply on every thread). Use when work is ready to push, when asked to open a pull request, or when a person says a review is waiting.
---

# review-and-pr

**This project's additions** go in `project.md` in this skill's folder, when it has any: an extension adds rules and
never weakens these. To relax or contradict a rule here, override this file in `framework.toml` with a reason that names
the rule.

Commands for the forge are shown for GitHub (`gh`). On another forge you need the same six operations: list a pull request's
inline comments, list its review bodies and issue-level comments, reply on a thread, resolve a thread, read the checks, and
find the repository's default branch.

## Before the pull request

1. **The gate.** `make check` (or `uv run python tools/check.py` where there is no make), run **unpiped** and its verdict
   read: a pipe after the command that decides swallows its exit code. If the project has no gate yet, say so in the pull
   request and do not claim a pass.
2. **Docs in the same pull request**, the ones [the definition of done](../../../Docs/standards/definition-of-done.md) lists
   (the board, the plan task ticked with its verification, the spec, the journal, the handoff, the ledger if the process
   failed). Do not keep a second list here.
3. **A pull request that lands a board row opens first, as a draft.** The row's `State: Landed` names the pull request
   (`landed-rows`, which the pre-commit hook runs), and the number exists only once it is open: commit the work with
   the row still in flight, push, `gh pr create --draft`, then mark the row landed with the number, run the review,
   and `gh pr ready` after it. A later commit is staged and committed as step 5 says and pushed; the pull request
   already exists, so its description is brought up to date with `gh pr edit <n> --body-file <file>` rather than
   created again, and its checks are read (step 7) before `gh pr ready`.
4. **The deliberate review** for a significant increment: run the `local-review` skill and paste its table into the pull
   request's *Review* section.
5. **Stage named paths**, not `git add -A`, and read `git status` first: a generated file or an unrelated reformat does not
   belong in the commit. **Commit with a person's identity, never an agent's**: `git commit -s` when `project.json` has `signoff` true, no
   attribution line for an AI. Write the commit message to a file in its own command, not chained to an assertion that could
   abort before writing it, or the commit reads a missing file.
6. **Push, then open the pull request** against the repository's own default branch (read it; do not assume it: `AGENTS.md`
   names it, or `git symbolic-ref refs/remotes/origin/HEAD`, or `gh repo view --json defaultBranchRef`). Give the body from
   `.github/pull_request_template.md` filled in, not typed over it: `gh pr create --base <default> --title "..."
   --body-file <file>`. Every two-way-door decision goes in *Decisions* (at most eight), what was verified, what is still open;
   an open gate is stated, never implied. **An issue the pull request fixes is named with `Closes #N`**, one line per
   issue, so the merge closes it; "answers #N" leaves it open after the fix lands. **Every number and every "cannot" in
   the body comes from a command run on the commit it names**, pasted, not recalled; read them again after each fix
   commit (framework 46).
7. **Read CI** on the pull request after pushing (`gh pr checks <n> --watch`): a claim of green comes after the run.

## Assessing an automated review

```bash
gh api --paginate repos/<owner>/<repo>/pulls/<n>/comments --jq '.[] | "\(.id) \(.path):\(.line)\n\(.body)\n"'
gh api repos/<owner>/<repo>/pulls/<n>/reviews --jq '.[].body'      # review bodies: some findings are only there
gh api repos/<owner>/<repo>/issues/<n>/comments --jq '.[].body'    # issue-level comments
gh pr checks <n> --watch
```

Read the review body for a "suppressed comments" section, if the reviewer has one, and assess those with the threads.

For each finding: decide valid or not **from the code, not from the comment's confidence**. Automated reviewers are right
about most things and wrong about some; the one that is wrong is wrong with the same confidence. Then:

- **Valid:** fix it, and test the fix.
- **Wrong:** refute it with evidence (a test, a spec line, a measured number), never with an assertion.
- **Valid but out of scope:** open a tracker issue before the pull request merges and put its number in the reply; never
  write "follow-up" with no number.

Reply on the thread, then resolve it:

```bash
gh api -X POST repos/<owner>/<repo>/pulls/<n>/comments/<id>/replies -f body="..."
gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<thread id>"}){thread{isResolved}}}'
```

A reply states what was done, or why not, and names the commit only after the commit exists. A claim in a reply is made after
the evidence exists. **Every thread gets a reply before the merge**, a wrong finding as much as a valid one: list the
threads again after the last push (`gh api graphql` with `reviewThreads { isResolved }`) and answer any left open. An
unanswered thread is a finding nobody decided. Update the pull request body (the test count, the *Review* section, any decision you added), and wait for
CI on the fix commit. A CI failure the reviewer did not mention is still yours.

Before merging, or asking a person to merge, a pull request that others are stacked on, retarget the stack to the default
branch (`gh pr edit <n> --base <default>`): deleting the branch closes a pull request based on it, and a closed pull request
cannot be reopened or retargeted.

Do not touch a pull request, branch or review you did not create in this session without asking whose it is.

A person on the roster merges and deletes the branch (their own work included); an agent never merges.
