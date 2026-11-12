# ADR 0010: Shared CI, one toolchain, and the nightly family check

Status: proposed, for the owner's review (it refines the Defaults in the brief, sections 3.8 and 3.9). 13 November 2026.

## Context

Six repositories each carry their own `ci.yml`. They do the same things in slightly different ways: the same lint,
tests, web build, accessibility check and Docker build, with versions written out in each file. The brief asks for
shared workflows in this repository (public, so the public sites can call them), one toolchain, one dependency-update
configuration, and a nightly check of the live family that also covers health, a real question, reports waiting,
statistics and key pages.

Reading the six workflows shows one thing the brief's sketch doesn't allow for. The accessibility check and the
smoke checks need the site **running**, and each site gets there differently: Where MPs Stand starts its Docker
image on sample data, Where Countries Stand starts with an empty data folder, Where Landlords Stand fetches and loads
real files first. A reusable workflow is a whole job; it cannot take "the site's own steps first".

## Options for the CI layout

1. **Reusable workflows only** (the brief's sketch). Simple to call, but the accessibility job would have to
   accept a "how to start the site" script as a string input, which hides each site's real steps in a parameter.
2. **Composite actions only.** Every site keeps its own jobs and calls shared steps. Flexible, but each site still
   lays out the same four jobs by hand, which is how they drifted.
3. **Both, each where it fits (recommended).** Reusable workflows for jobs that are the same everywhere; composite
   actions for steps that run inside a site's own job after it has set the stage.
4. **A template copied into each repository,** checked for drift. This is what the family kit does for pages, and
   the kit's history (a `--check` in every CI) shows the cost: a copy per repository to keep in step.

## Decision: option 3

In this repository:

| Kind | Name | What it does | Used by |
|---|---|---|---|
| Reusable workflow | `python.yml` | `uv sync --frozen`, `ruff`, the type check if the site has one, `pytest`; optionally again with the lowest and highest supported versions of named libraries | the four Python sites, this package |
| Reusable workflow | `web.yml` | `npm ci`, type check, tests, build, in a named folder | MPs, Councils, Lives, the hub |
| Reusable workflow | `kit.yml` | the family kit check (`sync.mjs --check`, or the version stamp while the kit is private) | every site and the hub |
| Reusable workflow | `docker.yml` | builds the image with the layer cache and runs one command in it | the four Python sites |
| Composite action | `setup` | the toolchain: Python, `uv`, Node, at the versions below | every workflow above, and a site's own jobs |
| Composite action | `a11y` | installs Playwright and axe at fixed versions and runs the site's `scripts/a11y.mjs` against an address the site's job has already started | each site's own smoke job |

- **The toolchain is written once,** as the defaults of the `setup` action: Python 3.12, `uv` 0.11.32, Node 22,
  and the Playwright and axe versions. A site's Dockerfile still names its base images (Docker can't read an
  action's inputs); a test in each site's CI compares the Dockerfile's versions with the action's, so they can't part.
- **Sites call the workflows at the same tag as the package they pin** (`rj-mitchell/wts-core/.github/workflows/python.yml@v0.1.0`),
  so a site has one number to raise and CI can't change under it.
- **Each site's `ci.yml` keeps only what is its own:** its fixtures, how it starts, its smoke pages.
- **This package's own CI uses the same workflows,** so they are exercised on every pull request here.
- **Dependency updates:** Dependabot, the same file shape in every repository, weekly and grouped, with
  `anthropic`, `lancedb` and `fastembed` in their own group, whose pull requests say an evaluation run is needed.
  Dependabot rather than Renovate: it is built into GitHub, needs no app installed on the account, and its grouping
  is enough for this.
- **Screenshot comparisons** on pull requests are left as a later, separate, non-failing workflow (`screenshots.yml`).
  The `a11y` action's inputs (the address, the widths, the colour schemes) are shaped so that it can share them.

## The nightly family check

It stays in the charity repository (`family-check.yml`, `family/tools/family-check.mjs`), changes nothing on any
site, and gains five checks. What each needs:

| Check | How | Fails when |
|---|---|---|
| Health | `GET /api/health` and `/api/status` | either doesn't answer, or the last finished data update is older than the site's own schedule allows (twice a day: 36 hours; daily: 60 hours; weekly: 9 days) |
| A real question, AI sites | `POST /api/ask` with one of a small set of fixed questions, with the check token | no final event, an error event, no citations, or any invalid citation. The time taken is recorded |
| Reports and statements waiting | `GET /api/check` with the check token | anything is older than 4 working days (so the policy's 5 is kept). Counts and ages only |
| Weekly statistics | `GET /api/check` returns the latest weekly figures; the family summary is written to the run's summary once a week | never (it reports) |
| Key pages | the home, "If you're named" and corrections pages load; internal links on them resolve; axe finds nothing serious or critical | a page fails, a link is broken, or axe finds a serious problem |

**Options for how the check learns what is waiting:**

1. A public count (`/api/waiting`). No secret, but it tells anyone how many complaints a site has open.
2. Each site's own admin token. Four secrets to make and keep, and only Where MPs Stand has admin endpoints today.
3. **One check token for the family (recommended):** one endpoint from the package on every site, `GET /api/check`,
   which answers only to a bearer token and returns counts, ages and statistics, never content. The owner makes one
   random value and sets it in two places: the charity repository's Actions secrets (`FAMILY_CHECK_TOKEN`) and each
   site's `deploy/.env` (`<PREFIX>_CHECK_TOKEN`).

The same token does two more jobs for the real question. It lets that one request skip the answer cache: otherwise
the same question would be served from the cache six nights in seven and prove nothing. And it marks the briefing's
record as a check, so the nightly question never appears in the statistics, the themes or the proposed test
questions. The token grants nothing else: it can't read reports, publish statements or change anything.

With no token set on a site, `/api/check` answers 404 and the nightly check reports "not set up" for that site
rather than failing, so the check can be merged before the owner has made the secret.

**Cost:** one question a night on three sites, about 3p each, about £33 a year. The check's questions are fixed and
kept in the charity repository, so they can be reviewed.

## Consequences

- A CI change is a package release. That is deliberate (CI can't change under a site), and patch releases are cheap
  (ADR 0006, 0007).
- The check token is a new secret on the server. It is read-only by design, and the endpoint is rate-limited like
  any other.
- Where Landlords Stand's weekly alert on waiting reports is retired when its nightly check is on, as the brief says.
