# Review rubric (canonical)

The single source of truth for the local standards reviewer: ten metrics, scored out of ten, 7 as the baseline.

## Metrics

Score each metric **1 to 10**. Mark a metric `n/a` when it does not apply to the code under review; do not score it.

| Metric | Focus |
| --- | --- |
| Design | Interface and API shape, cohesion, single-purpose units, YAGNI |
| Architecture | Fit with existing patterns; module boundaries; coupling; reuse over reinvention |
| Readability | Naming, structure, matches the surrounding style |
| Maintainability | Cost of change, testability, isolation |
| Performance | Obvious waste; hot-path cost; I/O where it should not be |
| Security | Input trust boundaries, paths from outside, injection, secrets in code, unsafe `eval`/`exec`/deserialisation |
| Error handling | Specific exception types, context on re-raise across layers, empty/None/out-of-range paths, no partial writes, a failure that is reported and not swallowed, and the error-path checklist in `testing.md` where the repository has one |
| Logging | Consistent logger use, appropriate levels, a run that leaves a record of what it read, decided and wrote, no stray `print()` outside an entry point |
| Coding standards | The repository's own conventions (columns, imports, type hints, module header, formatting) and **vocabulary**: a new domain noun with no row in the glossary, or a word the glossary already uses for another concept, is a finding |
| Layering | *When applicable*: separation of concerns; do not force it on code that is not layered this way |

## Baseline

**7/10 per metric is the bar** a change should clear. Call out every metric scoring **below 7** with a concrete fix and a
`file:line` anchor. **Do not inflate scores to be agreeable**: an honest 5/10 with a clear path to 8 is more useful than a
polite 7. Prefer the repository's discovered standards over generic preference; where they are silent, apply idiomatic
defaults for the language.

A failing gate (`make check` or any of its stages, including the hygiene and docs checks) is a hard finding regardless of
score; so is a design, spec or plan without its *Terms introduced* section where no docs check yet catches it, and so is
an error-path case the *Error paths* table marks "missing". **Any hard
finding makes the verdict `needs work`.** If the project has no gate yet, say so in the report; do not claim a pass.

## Output template

Return exactly this shape (drop *Below baseline* if nothing is under 7):

```
## Local Standards Review — <mode> (<target>)

| Metric | Score | Notes |
|--------|:-----:|-------|
| Design | 8/10 | <one line> |
| Architecture | 7/10 | <one line> |
| Readability | 9/10 | <one line> |
| Maintainability | 7/10 | <one line> |
| Performance | n/a | <why not applicable> |
| Security | 8/10 | <one line> |
| Error handling | 6/10 | <one line> |
| Logging | 8/10 | <one line> |
| Coding standards | 7/10 | <one line> |
| Layering | n/a | <why not applicable> |

### Hard findings
- <a hygiene match, a failing gate, a missing Terms introduced section, or "none">

### Error paths
<!-- Required whenever the change reads the filesystem, runs a subprocess, calls the network, or parses text it did
not write; otherwise one line saying none does. For each such function, one row per case of the error-path checklist
in Docs/standards/testing.md that applies to it: the test that covers it, or "missing" (a Hard finding), or
"n/a" with the reason. Probe a "missing" case where you can. A checklist only consulted is the one that failed. -->
| Function | Case | Covered by |
|----------|------|------------|
| `path/to/file.py:walk` | a folder it cannot list | `test_x` / missing / n/a: <why> |

### Below baseline (< 7)
- **Error handling** (`path/to/file.py:42`) — <what is wrong> → <concrete fix>

### Verdict
<pass | needs work> — <1–2 sentence summary>. Lowest applicable metric: <x>/10.
```
