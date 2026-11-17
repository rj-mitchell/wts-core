# ADR 0004: How a site plugs in its own parts

Status: accepted, 13 November 2026.

This record decides how a site gives the package what is its own: settings, wording, word lists and behaviour.

## Context

Each site has things the package must never hard-code: its settings prefix and own settings, its word list, its
wording for every refusal, its grouping of sources, its caps and prices, the pages a statement can sit beside, and
what goes in a backup. Before the package these were constants and default arguments scattered through each
site's copy of the engine, which is why a "shared" module differed in a dozen small places from site to site.

## Options

1. Subclassing throughout: a site subclasses `Settings`, `Verifier`, the backup job and so on, and overrides
   methods. Then nothing says what a site may change, and an upgrade can break an override silently.
2. Configuration only: everything a site varies is a key in `settings.toml`. Fine for numbers and names; wrong
   for wording, patterns and behaviour, which belong in reviewed code with tests.
3. Module-level registration (`wts_core.configure(prefix=…)`): hidden global state, so two sites' settings
   cannot exist in one test run.
4. A mix, each kind of variation in its natural form.

## Decision

Option 4.

| What varies | Form | Why |
|---|---|---|
| The site's own settings | a subclass of `wts_core.settings.Settings` with its own properties | the base holds the loading rules and the shared accessors |
| Numbers and names an operator may change (caps, prices, models, limits, thresholds, experiments) | `config/settings.toml`, checked at start-up | they are configuration |
| Facts fixed in code (name, package, prefix, hosts, instructions version) | one frozen `Site` object | one place to read what makes this site this site |
| Wording a reader or sender sees | frozen `Messages` and `ReplyMessages` objects with no defaults | the package holds no wording, so it cannot change a site's by accident, and a new message fails loudly until each site supplies it |
| The loaded-words list and the verifier's patterns | values passed to the checks, with the family's common list exported to extend | each site's list is its own on purpose |
| Behaviour that follows the site's record (the pipeline, where a statement may sit, how a test question is asked) | small `Protocol`s the site implements | typed, testable with fakes, and the package cannot reach past them |
| Optional steps in the flow of a briefing | the briefing desk's hooks (ADR 0009) | named points instead of open-ended overriding |

Rules:

- No global state. Everything is passed in, so two sites can be built in one process, which is how the example
  site and the contract tests run.
- Nothing reader-facing, and no limit or price, has a default in the package. Start-up fails, naming the key, if
  one is missing.
- Every extension point is listed in [`EXTENDING.md`](../EXTENDING.md) with an example from the example site,
  which CI runs. An extension point the example does not use is not a supported one, unless `EXTENDING.md` marks
  it as an exception.
- Subclassing anything but `Settings` and `briefing.Hooks` is not supported.

## Consequences

- Moving a site onto the package gathered its scattered constants into one `Site`, one `Messages` and its
  `settings.toml`, with parity tests proving that no setting, message or limit changed on the way.
- A site's `site.py` is the page a newcomer reads first: everything that makes one site different from another,
  in one file.
