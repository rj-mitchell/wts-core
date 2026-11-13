# ADR 0006: How the sites take the package: a wheel from a tagged release

Status: accepted by the owner on 13 November 2026.

## Context

Each site must be able to install the package in three places: a developer's machine, GitHub Actions, and the
site's Docker build on the shared server. The repository is public, and no build may need a token. The brief's
default is `uv` installing from a git tag (`wts-core @ git+https://github.com/rj-mitchell/wts-core@v0.1.0`), with
`git subtree` vendoring as the fallback, and not PyPI.

One fact decides this. `uv` shells out to `git` to install a `git+https` dependency, and three of the four images
have no `git`: Where Countries Stand, Where Councils Stand and Where Landlords Stand build on
`python:3.12.15-slim` and install only `ca-certificates`. Only Where MPs Stand's image installs `git` (for its
parlparse data). So the default would break three Docker builds unless `git` were added to each image.

## Options

| | A. git tag (the brief's default) | B. A wheel attached to a GitHub release (recommended) | C. `git subtree` vendoring |
|---|---|---|---|
| What a site writes | `wts-core[ai] @ git+https://github.com/rj-mitchell/wts-core@v0.1.0` | `wts-core[ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.1.0/wts_core-0.1.0-py3-none-any.whl` | nothing: the code is copied into `vendor/wts_core` |
| Needs `git` in the image | Yes: add it to three images (about 60 MB each, and one more program to keep patched) | No | No |
| Needs a token | No | No | No |
| What `uv.lock` pins | the commit | the file's SHA-256 | nothing (the copy is the pin) |
| Build at install time | Yes: `uv` builds the wheel from source, fetching the build backend from PyPI | No: the wheel is ready-made | No |
| Reaches | `github.com` | `github.com` and GitHub's release-download host | nothing at build time |
| Copies can drift again | No | No | Yes: a hot fix made in place is exactly how the four copies drifted |
| A release is | a tag | a tag, plus a workflow that builds the wheel and attaches it | a tag, plus a subtree pull in every site |

## Decision

**B.** A release workflow in this repository runs when a `v*` tag is pushed: it runs the full test suite, builds the
wheel and the source archive, and attaches both to a GitHub release. Sites depend on the wheel's address, with
their extras, and `uv.lock` records its hash, so a changed file fails the build rather than slipping in.

A is kept as the documented fallback for trying an unreleased commit on a developer's machine (where `git` is
always present). C is rejected: it reintroduces the fault this package exists to remove.

Not PyPI, as the brief says: the name would need guarding, and nothing here needs it.

## Consequences

- No image changes. The server's Docker builds must reach GitHub's release-download host as well as `github.com`:
  one line for OPERATIONS.md's "hosts the server must reach".
- A release needs one more moving part (the workflow). It is small, and the package's own CI exercises the same
  build on every pull request, so a broken build is caught before a tag.
- Dependency-update tools don't raise direct-address dependencies by themselves. `docs/UPGRADING.md` gives the
  two-line change, and the drift check (phase 5) fails a site that is more than one minor version behind.
- **To verify in phase 3, before any site adopts:** a site's `uv lock` and `uv sync --frozen` with the wheel
  address, inside `python:3.12.15-slim` with no `git`, and in GitHub Actions. If it fails for a reason not seen
  here, fall back to A and add `git` to the three images, recorded in this ADR.
