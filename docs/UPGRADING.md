# Upgrading: a new version, a fix, a release

Four sites pin this package and one person keeps them all. So an upgrade has to be boring: a site knows from the
version number and the changelog whether it must change anything, and a fix reaches every site the same way
([ADR 0006](adr/0006-distribution.md), [ADR 0007](adr/0007-versioning.md)).

## Moving a site to a new version

1. **Read [`CHANGELOG.md`](../CHANGELOG.md)** for every version between the one the site pins and the new one.
   Each entry under "Changed" says what a site must do. While the version is 0.x a minor version (0.1 to 0.2) may
   change the interface; a patch version (0.2.0 to 0.2.1) may not.
2. **Raise the version in the site's `pyproject.toml`.** The dependency is the address of the release's wheel,
   and the version is in it twice, once in the tag and once in the file's name:

   ```toml
   dependencies = [
       "wts-core[cli,offsite,duckdb,ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.2.0/wts_core-0.2.0-py3-none-any.whl",
   ]
   ```

   Leave `[tool.hatch.metadata] allow-direct-references = true` as it is: without it the build refuses a
   dependency written as an address.
3. **Run `uv lock`.** The lock file records the new wheel's hash, so a file changed after the release fails the
   build. Then `uv sync`.
4. **Raise the shared workflows' tag to the same version,** wherever the site's `.github/workflows/` call them:

   ```yaml
   uses: rj-mitchell/wts-core/.github/workflows/python.yml@v0.2.0
   ```

   The same for `kit.yml`, `docker.yml`, `web.yml` and the `setup` and `a11y` steps. A site has one number, and
   it is the same in both files. Dependabot is told to leave `rj-mitchell/wts-core*` alone, so that it cannot
   raise the workflows' tag without the wheel ([`NEW-SITE.md`](NEW-SITE.md), step 9).
5. **Make the changes the changelog asked for,** and run the site's own checks: `uv run ruff check .`,
   `uv run mypy`, `uv run pytest`, and the free replay of its recorded briefings (`<site> eval replay
   eval/fixtures`). If the version changed the checks on briefings or anything a briefing is written with, make
   an evaluation run before and after, and commit both.
6. **One pull request in the site,** holding nothing but the upgrade. When CI is green and it is merged, the
   owner runs the site's `update.sh` on the server. The image fetches the wheel from GitHub's release-download
   host: no `git` and no token.

The package's tables look after themselves. Migrations only ever add, and run the first time the site starts on
the new version. To go back, pin the earlier version again: it finds its tables as it left them, and any table
or column the newer version added is ignored.

Take a new version to one site at a time, in the order [`MIGRATION.md`](MIGRATION.md) gives for adoption (Where
Landlords Stand, Where Councils Stand, Where Countries Stand, Where MPs Stand), so that a fault shows on the
smallest site before it reaches the largest.

## How a fix flows

One way only:

1. **Fix it in the package,** with a test that fails without the fix
   ([`CONTRIBUTING.md`](../CONTRIBUTING.md)).
2. **Release it** as a new version. A release is never changed: a fix to a fix is another version. Fixes are
   cheap to release, so they go out as patch versions and do not wait for other work.
3. **One pull request in each site** that raises the pin, as above.

**A site never patches its installed copy.** It does not edit the package in its environment, copy a module of
the package into its own tree, replace a function of the package at run time, or import a private name to work
round a fault. That is how four copies drifted apart before, and it is what this package exists to end. If the
package cannot do what a site needs, the package is changed, or the need is met by one of the hooks in
[`EXTENDING.md`](EXTENDING.md).

To try an unreleased fix before it is released, on a developer's machine only: build the wheel from a checkout of
the package (`uv build --wheel`) and give its `file://` address in place of the release's. Never deploy a site
pinned that way.

## Releasing the package

The steps are in [`CONTRIBUTING.md`](../CONTRIBUTING.md), under "Releasing". In short:

1. In a pull request: the version in `pyproject.toml` and in `src/wts_core/__init__.py`; the changelog's entry
   headed `## <version> (<date>)`, with what changed, what a site must do for each change, and its `api:` line
   (`WTS_UPDATE_API=1 uv run pytest tests/test_public_api.py -s` writes `docs/api-snapshot.txt` and prints the
   line); `uv lock` here and in `examples/minimal-site`.
2. When it is merged: on GitHub, Actions, "Release", "Run workflow" on `main`, with the version. The workflow
   checks that the three places agree, runs the tests, builds the wheel, makes the tag `v<version>` on that
   commit and attaches the wheel to a release.
3. Then one pull request in each site, as in the first section.
