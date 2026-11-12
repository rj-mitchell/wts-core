# Phase 0: what was checked before any design or code

13 November 2026. Each item below was checked in the build session, not assumed; the evidence is beside it.

## 1. The repository

| Check | Result | Evidence |
|---|---|---|
| `rj-mitchell/wts-core` exists and is public | Yes | GitHub's API reports `"private": false, "visibility": "public"`; `LICENSE` loads from `raw.githubusercontent.com` with no token |
| It was empty | Yes | `git ls-remote --heads` returned nothing |
| Licence | Added: AGPL-3.0, the same file as the four sites (byte-identical to Where MPs Stand's `LICENSE`) | commit `4ea57ba` on `main` |
| A branch to open pull requests against | `main` now holds one commit: the licence and a placeholder README | the same commit |

That first commit went straight to `main`, because a pull request needs a branch to open against and the repository
had none. Everything else arrives by pull request.

**One thing found that changes the plan.** Three of the four sites' Docker images (Countries, Councils, Landlords)
have no `git` in them (`python:3.12.15-slim` plus `ca-certificates` only; only Where MPs Stand's image installs
`git`). `uv` needs `git` to install a `git+https://…@tag` dependency, so the brief's default way of taking the
package would fail in those three images unless `git` were added to each. The design therefore recommends
installing a wheel attached to a tagged GitHub release instead (ADR 0006): no `git` needed, the file's hash is
recorded in `uv.lock`, and the repository still needs no token.

## 2. The drift check, re-run on today's `main` branches

`python3 family/tools/drift.py --root /home/user --limit 0`, with the sites at `de8b3f4` (MPs), `aa085c6`
(Countries), `10a79f7` (Councils) and `c240d7f` (Landlords), all 12 November 2026.

Pairs further apart than the accepted baseline (the report marks them `!`):

| Module | Pair | Alike | Change | Functions that differ |
|---|---|---|---|---|
| The citation verifier | MPs ↔ Councils | 0.97 | −0.03 | `_classify_uncited`, `_is_lead_in_piece`, `recheck_flags`, `verify`, module level |
| Cost accounting | MPs ↔ Councils | 0.30 | −0.06 | `cost_usd`, `prices_for` |
| | Countries ↔ Councils | 0.36 | −0.06 | `cost_usd`, `prices_for` |
| | MPs ↔ Countries | 0.82 | −0.11 | `cost_usd`, `prices_for` |
| Backup | MPs ↔ Countries | 0.43 | −0.04 | `make_backup`, `restore_backup`, module level |
| | Countries ↔ Councils | 0.63 | −0.28 | `make_backup`, `restore_backup` (only Countries), module level |
| | Countries ↔ Landlords | 0.03 | −0.02 | `make_backup`, `restore_backup` (only Countries), module level (only Countries) |
| Off-site copies to B2 | Countries ↔ Councils | 0.94 | −0.05 | `backup_alerts`, `check` |
| | Countries ↔ Landlords | 0.89 | −0.10 | `backup_alerts` (only Countries), `check`, module level |
| | Councils ↔ Landlords | 0.89 | −0.10 | `backup_alerts` (only Councils), `check`, module level |

This differs from the brief's notes in two ways, both because work has moved on since they were written:
Countries now has `restore_backup` and `backup_alerts` (so MPs is no longer the only copy with either), and the
verifier's only pair below baseline is MPs ↔ Councils.

Every pair, including those that moved closer, is in the full report kept with the design:
[`study/drift-2026-11-13.txt`](study/drift-2026-11-13.txt).

## 3. Library versions the package targets

| Library | Target | Why |
|---|---|---|
| Python | 3.12 and 3.13 (tested on both); the sites run 3.12 | Every site already requires ≥ 3.12 and builds on `python:3.12.15-slim` |
| `anthropic` | 2.x (lowest tested: 2.3.0, what Countries and Councils lock today) | The AI slice can serve one major version; MPs moves up in its own pull request |
| `duckdb` | 2.x (lowest tested: 2.0.0) | As above |
| `fastapi` | not a dependency of the package at all | The briefing streamer is a plain generator of bytes; only the example site and the sites themselves use FastAPI. The package's CI still runs the example site against the lowest and highest FastAPI the sites use |
| `lancedb` | ≥ 0.40 | All three AI sites lock 0.40.0 |
| `fastembed` | the version the three AI sites lock | Search by meaning must give the same vectors after adoption |

## 4. What the nightly family check (brief 3.9) will need from each site

Today the check needs no secrets. The table shows what exists and what each new check needs.

| Check | Where MPs Stand | Where Countries Stand | Where Councils Stand | Where Landlords Stand |
|---|---|---|---|---|
| Health | `/api/health`, `/api/status` exist | both exist | both exist | `/api/health` exists; no `/api/status` |
| Last data update finished recently | `/api/status` (to confirm it carries the time) | `/api/status` | `/api/status` | needs a small addition |
| A real question | `/api/ask` exists | `/api/ask` exists | exists | not applicable (no AI) |
| Reports and statements waiting | admin endpoints exist behind `HANSARD_ADMIN_TOKEN` | no admin endpoints | no admin endpoints | no admin endpoints |
| Weekly statistics | arrives with the package | the same | the same | the same (no briefings; reports only) |

**The design's recommendation (ADR 0010):** one new endpoint on every site, from the package, `GET /api/check`,
which answers only to a bearer token and returns counts and times, never content: reports and statements waiting
and the age of the oldest in working days, the time of the last finished update, and the latest weekly statistics.
The same token lets the nightly question skip the answer cache (otherwise the same question would be answered from
the cache on six nights out of seven and test nothing) and marks its record as a check, so it is left out of the
statistics.

**Secrets the owner would add** (none exists yet; nothing is ever written in a file in a repository):

| Where | Name | What it is |
|---|---|---|
| The charity repository's Actions secrets | `FAMILY_CHECK_TOKEN` | One long random value, made by the owner |
| Each site's `deploy/.env` on the server | `HANSARD_CHECK_TOKEN`, `WCS_CHECK_TOKEN`, `COUNCILS_CHECK_TOKEN`, `LANDLORDS_CHECK_TOKEN` | The same value |

Until the secret is set, the nightly check keeps doing what it does today and reports the new checks as "not set
up" rather than failing.

## 5. Other facts established

- An Anthropic API key for evaluation runs is present in the build session (`HANSARD_ANTHROPIC_API_KEY`). The sites'
  data (search indexes, Parquet files, 0.2 to 34 GB a site) is not, so a full evaluation run of a site's own
  question set cannot be made from the build session. See `PROGRESS.md` for what was run instead.
- The toolchain already agrees in the images (Python 3.12.15, `uv` 0.11.32, Node 22.23.4); the differences are in
  CI (Where MPs Stand: `setup-uv@v3` with `uv` 0.5.11; Where Countries Stand: no `uv` version set).
- Every site's command line is a Typer app (`<package>.cli:app`), and every site's state database is SQLite.
