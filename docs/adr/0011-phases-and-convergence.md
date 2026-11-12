# ADR 0011: What to converge before the package, and what to converge by adopting it

Status: decided (a Default: "the order of adoption and how the phases are split"). 13 November 2026.

## Context

The brief's phase 1 asks for the four copies to be brought together first, until every base module is 0.95 alike or
more between every pair that shares it, and only then for the package to be built from the converged copies.

The drift report and a reading of every copy show that the differences are of three kinds:

1. **A fix one copy has and the others lack.** For example, Where MPs Stand re-judges a saved briefing's lead-ins
   as a new briefing's are judged, and the others don't; Where Countries Stand deletes notes of failed briefings
   after 90 days, as its privacy notice says. These change what a site does.
2. **A site doing the same job its own way.** Where Councils Stand keeps its answer cache as methods of its state
   database rather than functions; Where Landlords Stand's backup is a command in its `cli.py` that gzips one
   SQLite file; each site's caps have their own wording and defaults. The similarity score is low, but nothing is
   missing.
3. **Each site's own parts,** which are different on purpose: word lists, the settings accessors, default grouping.

Making kind 2 "0.95 alike" would mean rewriting working code in three repositories to match a fourth, with tests,
review and a deploy each, and then deleting all four copies a few weeks later when the package is adopted. The
rewrite is where the risk is, and it would be taken twice.

## Options

1. **Converge everything first** (the brief's default). Clean starting point; pays for every structural rewrite
   twice.
2. **Converge nothing; let the package be the convergence.** Cheapest, but then each adoption changes behaviour
   and structure in the same pull request, and a parity test can't tell a deliberate fix from a regression.
3. **Port the fixes now; converge structure by adopting (recommended).**

## Decision: option 3

- **Phase 1 ports every kind-1 difference** to every copy that lacks it, one pull request a site, each fix with its
  test, following ENGINE.md's rule. After phase 1 the sites *behave* alike wherever they are meant to, and readers
  get the fixes whether or not the package ships on time.
- **Kind 2 is converged once, by adoption** (phase 4), with parity tests that pin each site's current behaviour
  first (ADR 0009, MIGRATION.md).
- **Kind 3 stays in the sites for good,** behind the extension points (ADR 0004).
- **The drift check is told which is which.** `shared-modules.json` gains the right-of-reply modules, and each
  module's record lists the symbols that are a site's own, so the report measures what should be alike and the
  baseline can be held at a level that means something. The 0.95 target is kept for the modules and functions
  where it is honest (the verifier, British spelling, the embedder, cost, the limiter, the visitor code, the
  in-progress count); for the rest the report says "converges on adoption" instead of showing a number that looks
  like neglect.

Adoption order is unchanged from the brief: Where Landlords Stand, Where Councils Stand, Where Countries Stand,
Where MPs Stand.

## Consequences

- Phase 1's pull requests are small and each changes behaviour in a way its description states.
- The drift report after phase 1 will still show low numbers for backup, the answer cache and settings between some
  pairs. `docs/MIGRATION.md` lists each, with the parity test that will cover it at adoption.
