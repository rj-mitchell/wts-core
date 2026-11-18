# ADR 0006: How the sites take the package: a wheel from a tagged release

Status: accepted, 13 November 2026.

This record decides how a site installs the package.

## Context

Each site installs the package in three places: a developer's machine, GitHub Actions, and the site's Docker
build on the shared server. The repository is public, and no build may need a token.

One fact decides it. `uv` runs `git` to install a `git+https` dependency, and three of the four sites' images
(`python:3.12.15-slim`) have no `git`. Only Where MPs Stand's image installs it, for its own data.

## Options

| | A. A git tag | B. A wheel attached to a GitHub release | C. `git subtree` vendoring |
|---|---|---|---|
| What a site writes | `wts-core[ai] @ git+https://github.com/rj-mitchell/wts-core@v0.3.2` | `wts-core[ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.3.2/wts_core-0.3.2-py3-none-any.whl` | nothing: the code is copied into the site |
| Needs `git` in the image | yes, in three images (about 60 MB each) | no | no |
| What `uv.lock` pins | the commit | the file's SHA-256 | nothing |
| Built at install time | yes, fetching the build backend | no | no |
| Copies can drift again | no | no | yes: a fix made in place is how the copies drifted before |

PyPI was not considered: the name would need guarding, and nothing here needs it.

## Decision

B. The `Release` workflow runs the tests, builds the wheel and the source archive, tags the commit
`v<version>` and attaches both files to a GitHub release. Sites depend on the wheel's address with their extras,
and `uv.lock` records its hash, so a changed file fails the build. C is rejected: it brings back the drift this
package exists to end. To try an unreleased commit, a developer builds the wheel locally and points to it
([`UPGRADING.md`](../UPGRADING.md#a-fix-to-the-sites)).

## Consequences

- No image changes. The server's Docker builds must reach `github.com` and `objects.githubusercontent.com`, to
  which a release's download address redirects. Both belong in the charity's `family/OPERATIONS.md`, "The hosts
  the server must reach".
- Hatchling, which every site builds with, refuses a dependency given by its address unless the site's
  `pyproject.toml` sets `[tool.hatch.metadata] allow-direct-references = true`.
- Dependency-update tools do not raise an address dependency. The maintainer raises it by hand
  ([`UPGRADING.md`](../UPGRADING.md)), and the family's nightly check reports a site that has fallen more than one
  minor version behind.
- CI installs every build of the wheel in `python:3.12.15-slim` with no `git` (the `slim-image` job). The first
  adoption, on 13 November 2026, also confirmed that `uv lock` and `uv sync --frozen` work against a release's
  address and that nothing in the install calls `git`.
