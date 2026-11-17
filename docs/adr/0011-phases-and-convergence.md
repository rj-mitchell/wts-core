# ADR 0011: What to converge before the package, and what to converge by adopting it

Status: accepted, 13 November 2026. Carried out: all four sites adopted the package by 16 November 2026.

This record decides how the four sites' copies of the shared engine were brought together into the package.

## Context

Before the package, each Python site carried its own copy of one engine, and the copies had drifted. The
differences were of three kinds:

1. A fix one copy had and the others lacked, which changes what a site does (for example, deleting notes of failed
   briefings after 90 days, as one site's privacy notice said).
2. The same job done a different way, with nothing missing (an answer cache written as methods instead of
   functions, a backup written as a command).
3. Each site's own parts, different on purpose (word lists, settings, grouping of sources).

Rewriting kind 2 in every copy to match before building the package would have meant rewriting working code in
three repositories, then deleting all four copies weeks later: the risk taken twice.

## Options

1. Converge everything in the copies first, then build the package from them.
2. Converge nothing first, and let each adoption change behaviour and structure in one pull request. A parity
   test could then not tell a deliberate fix from a regression.
3. Port the fixes first, and converge structure by adopting the package.

## Decision

Option 3.

- Every kind-1 fix was ported first to every copy that lacked it, one pull request a site, each with its test.
  The sites then behaved alike wherever they were meant to, whether or not the package shipped on time.
- Kind 2 was converged once, by each site's adoption, with parity tests that pinned the site's behaviour first
  (ADR 0009).
- Kind 3 stays in the sites for good, behind the extension points (ADR 0004).

Where MPs Stand, the largest site and the one with the most steps of its own, adopted the package last.

## Consequences

- The fix pull requests were small, and each said how it changed behaviour.
- The charity's drift check measures only what should be alike; a site on the package copies nothing, so it has
  nothing to drift.
