# ADR 0010: Shared CI, one toolchain, and the nightly family check

Status: accepted, 13 November 2026.

This record decides how the family's repositories share their CI and toolchain, and how the charity's nightly
check learns about each live site.

## Context

The family's six repositories each carried their own `ci.yml`, doing the same lint, tests, web build,
accessibility check and Docker build in slightly different ways, with versions written out in each file. The
accessibility check needs the site running, and each site gets there differently (a Docker image on sample data,
an empty data folder, real files fetched first). A reusable workflow is a whole job, so it cannot run "the site's
own steps first".

## Options for the CI layout

1. Reusable workflows only. The accessibility job would have to take "how to start the site" as a string input,
   which hides each site's real steps in a parameter.
2. Composite actions only. Each site still lays out the same jobs by hand, which is how they drifted.
3. Both, each where it fits: reusable workflows for jobs that are the same everywhere, and composite actions for
   steps that run inside a site's own job.
4. A template copied into each repository and checked for drift, which costs a copy per repository to keep in
   step.

## Decision

Option 3. In this repository:

| Kind | Name | What it does | Used by |
|---|---|---|---|
| Reusable workflow | `python.yml` | `uv sync --frozen`, `ruff`, the type check if the repository has one, `pytest`; optionally at the lowest or highest versions the ranges allow | the four Python sites, this package |
| Reusable workflow | `web.yml` | `npm ci`, type check, tests, build, in a named folder | the sites with a web front end |
| Reusable workflow | `kit.yml` | checks the `VERSION` stamp of the family kit the site synced (the kit is in the charity's private repository, so a site's CI cannot compare against the kit itself) | every site |
| Reusable workflow | `docker.yml` | builds the image with the layer cache and runs one command in it | the four Python sites |
| Composite action | `setup` | the toolchain: Python, `uv`, and Node when asked for | every workflow above, and a site's own jobs |
| Composite action | `a11y` | runs the site's `scripts/a11y.mjs` with Playwright and axe against an address the site's job has started | each site's own smoke job |

- The toolchain is written once, in `toolchain.toml`. The workflows and actions carry its versions as their
  defaults, and `tests/test_toolchain.py` fails if any disagrees. A site's Dockerfile still names its own base
  image, since Docker cannot read an action's inputs; a test in the site keeps the two the same.
- Sites call the workflows at the same tag as the package they pin, so a site has one number to raise and its CI
  cannot change under it. This package's own CI uses the same workflows, so they run on every pull request here.
- Each site's `ci.yml` keeps only what is its own: its fixtures, how it starts, its smoke pages.
- Dependency updates: Dependabot, weekly and grouped, in the same file shape in every repository, told to leave
  `rj-mitchell/wts-core*` alone so that the workflows' tag moves only with the package.

## The nightly family check

The check stays in the charity's repository (`family-check.yml`, `family/tools/family-check.mjs`) and changes
nothing on any site. Its design:

| Check | How | Fails when |
|---|---|---|
| Health | `GET /api/health` and `/api/status` | either does not answer, or the last data update is older than the site's schedule allows |
| A real question, on AI sites | `POST /api/ask` with one of a few fixed questions and the check token | no final event, an error, no citations, or any invalid citation |
| Reports and statements waiting | `GET /api/check` with the check token | anything has waited four working days, so that the policy's five are kept |
| Weekly statistics | the newest weekly totals, from `/api/check` (`weekly`) | never: it reports |
| Key pages | the home, "If you're named" and corrections pages load, their links resolve, and axe finds nothing serious | a page fails, a link is broken, or axe finds a serious problem |

Which of these the check runs today is in the charity's `family/OPERATIONS.md`, "The nightly check".

The check learns what is waiting from one read-only check token for the family. Every site answers
`GET /api/check` (the package's `cli.check_route`) only to that bearer token, with counts, ages, versions and
statistics, never content. The owner makes one random value and sets it as the charity repository's
`FAMILY_CHECK_TOKEN` secret and in each site's `deploy/.env` as `<PREFIX>_CHECK_TOKEN`. The alternatives were a
public count, which would tell anyone how many complaints a site has open, and an admin token per site, four
secrets to keep where only one site had admin endpoints.

The same token lets the nightly question skip the answer cache (otherwise it would be served from the cache six
nights in seven and prove nothing) and marks its record as a check, so it never appears in the statistics, the
themes or the proposed test questions. It grants nothing else. With no token set, `/api/check` answers 404 as if
it were not there. One question a night on three sites costs about 3p each, about £33 a year.

## Consequences

- A change to the shared CI is a package release, so CI cannot change under a site. Patch releases are cheap.
- The check token is a new secret on the server, read-only by design, and its route is rate-limited like any
  other.
