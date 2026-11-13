# ADR 0004: How a site plugs in its own parts

Status: accepted by the owner on 13 November 2026.

## Context

Each site has things the package must never hard-code: its settings prefix and its own settings, its word list, its
wording for every refusal, its default grouping, its caps and prices, the pages a statement can sit beside, what
goes in a backup and what the file is called. Today these are scattered through each copy as constants and default
arguments, which is why a "shared" module differs in a dozen small places from site to site.

The brief suggests a base `Settings` class to subclass, plus hooks for word lists, briefing defaults, caps and
prices.

## Options

1. **Subclassing throughout:** a site subclasses `Settings`, `Verifier`, `BackupJob`, `StatementRules`… and
   overrides methods. Familiar, but a subclass can override anything, so "what may a site change?" has no answer, and
   an upgrade can break an override silently.
2. **Configuration only:** everything a site varies is a key in `settings.toml`. Fine for numbers and names; wrong
   for wording a reader sees, patterns and behaviour, which belong in reviewed code with tests.
3. **Module-level registration** (`wts_core.configure(prefix="WCS", …)`). One call, but hidden global state: two
   sites' settings can't exist in one test run, and the example site and a real site can't be tested together.
4. **A mix, each kind of variation in its natural form (recommended).**

## Decision: option 4

| What varies | Form | Why |
|---|---|---|
| The site's own settings (`parlparse_dir`, `modgov`…) | **a subclass of `wts_core.settings.Settings`** with its own properties | properties on a settings object is what every site already has; the base holds the shared accessors (`answer`, `usage`, `pricing`, `data_dir`, `state_db`) and the loading rules |
| Names and numbers an operator may change (caps, prices, models, limits, thresholds, experiments) | **`settings.toml`**, validated at start-up | they are configuration today |
| Facts about the site fixed in code (its name, package, prefix, hosts, backup file pattern, what a backup holds, instructions version) | **one frozen `Site` object** the site builds once and passes in | data, not behaviour; one place to read what makes this site this site |
| Wording a reader sees (every refusal, limit and error message) | **a frozen `Messages` object** with one field per message and no defaults | the package holds no reader-facing wording of its own, so it can't change a site's by accident; a new message in a later release fails loudly until each site supplies its own |
| The loaded-words list; the verifier's honorifics | **values passed to the check** (`LoadedWords(pattern)`, `Verifier(honorifics=…)`), with the family's common list exported for sites to extend | each site's list is its own on purpose (ENGINE.md) |
| Behaviour that follows the site's record (the pipeline, finding sources only, where a statement may sit, how an eval question is loaded, grouping sources for the balance figures) | **small `Protocol`s** the site implements, passed in | typed, testable with fakes, and the package can't reach past them |
| Optional steps in the request flow | **the briefing desk's four hooks** (ADR 0009) | named points, not open-ended overriding |

Rules:

- **No global state.** Everything is passed in. Two sites can be built in one process, which is how the example
  site and the contract tests run.
- **Nothing reader-facing has a default in the package.** Limits and prices keep the defaults each site's code has
  today, but those defaults move into each site's `settings.toml` during adoption, so the package has none either.
  Start-up fails, naming the key, if one is missing.
- **Every extension point is listed in `docs/EXTENDING.md`** with an example taken from the example site, and each
  is exercised by the example site in CI. An extension point that the example doesn't use is not a supported one.
- **Subclassing anything but `Settings` is not supported,** and the classes say so.

## Consequences

- Adoption moves each site's scattered constants into one `Site`, one `Messages` and its `settings.toml`. That is
  most of each adoption's diff, and the parity tests (resolved settings, every message, every limit) are what prove
  nothing changed on the way.
- A site's `site.py` becomes the page a newcomer reads first: everything that makes Where Councils Stand different
  from Where Countries Stand, in about fifty lines.
