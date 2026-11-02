# Definition of done: HogNoise's additions

**Status:** Living. Extends [definition-of-done.md](definition-of-done.md): these items add to it and never weaken it.

- [ ] **Claims follow the vectors.** The README's status table calls a feature shipped only when committed vectors exercise
      it; anything else is wanted. Say where something is unmeasured. There is no GPU rung and no 4D yet, and "beyond the
      edge" stays an open slot, not a promise.
- [ ] **The README's numbers are re-measured** when a change could move them (the comparison counts, the timings), with the
      commit they were measured on.
- [ ] **Findability moves with the features.** A change that adds or removes a feature, or changes a README claim, updates
      [findability.md](../findability.md)'s surfaces in the same pull request: the README's *Who it's for*, `pyproject.toml`
      keywords, llms.txt, and the GitHub description and topics (and that table, their only record).
- [ ] **[PROVENANCE.md](../../PROVENANCE.md) is updated** when what was carried from the source project changes.
- [ ] **The three environments in [testing-project.md](testing-project.md) pass**, run, not assumed.
