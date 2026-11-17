# Documentation

Every document in this repository, what it covers and who it is for. "The maintainer" is the person who keeps
the package and the sites; "the owner" makes the decisions they need.

| Document | What it covers | For |
|---|---|---|
| [`../README.md`](../README.md) | what the package is, a quick start, and how a site installs it | anyone new to the project |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | the design, how a briefing flows through the package, and the main decisions | a developer or reviewer who wants the whole picture |
| [`adr/`](adr/) | twelve architecture decision records, each with its context, the options considered and the reason for the choice | anyone asking why something is the way it is |
| [`EXTENDING.md`](EXTENDING.md) | every hook a site plugs its own parts into, each with an example from the example site | the maintainer building or changing a site |
| [`NEW-SITE.md`](NEW-SITE.md) | the checklist for a new site, from copying the example to the day it is announced | the maintainer starting a site |
| [`UPGRADING.md`](UPGRADING.md) | moving a site to a new version, deploying it, and putting a site back on its old code until 1 February 2027 | the maintainer of a site |
| [`IMPROVING.md`](IMPROVING.md) | the weekly routine: reading the statistics, alerts, growing the test sets, running an experiment | the maintainer of a site with briefings |
| [`../CHANGELOG.md`](../CHANGELOG.md) | what changed in each version, and what a site must do | the maintainer of a site |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | the rules for changing the package, style, tests, and how a release is made | anyone changing the package |
| [`api-snapshot.txt`](api-snapshot.txt) | the public interface, written out by `tests/test_public_api.py` | the tests; a reviewer checking an interface change |
| [`../examples/minimal-site/`](../examples/minimal-site/) | Where Parks Stand, an invented site that uses every part of the package and that CI runs end to end | anyone who wants working code to copy |
| [`../src/wts_core/testing/recorded/README.md`](../src/wts_core/testing/recorded/README.md) | the recorded model streams the tests replay, and how to record another | a developer writing tests or a new model adapter |

The decision records:

| Record | Decides |
|---|---|
| [0001](adr/0001-slices-and-module-boundaries.md) | the base install and its extras, and the modules |
| [0002](adr/0002-ports-and-adapters.md) | the interfaces the model, embedder, index and stores are swapped behind |
| [0003](adr/0003-event-format.md) | the event format of a streamed briefing |
| [0004](adr/0004-how-sites-plug-in.md) | how a site gives the package its settings, wording and behaviour |
| [0005](adr/0005-state-database.md) | the package's own tables, a site's one-off import, and deleted data |
| [0006](adr/0006-distribution.md) | installing the package as a wheel from a tagged release |
| [0007](adr/0007-versioning.md) | versions, the public interface and compatibility |
| [0008](adr/0008-reports-and-statements.md) | readers' reports, the corrections log and the right of reply |
| [0009](adr/0009-briefing-desk.md) | the briefing desk, which runs the flow of every briefing |
| [0010](adr/0010-ci-and-nightly-check.md) | the shared CI workflows, the toolchain and the nightly family check |
| [0011](adr/0011-phases-and-convergence.md) | how the sites' copies of the engine were brought together |
| [0012](adr/0012-briefing-record-and-statistics.md) | the record of each briefing, retention, statistics, alerts and experiments |
