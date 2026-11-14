"""Settings: a TOML file, a per-installation file layered over it, and overrides; and the facts about a site.

The loader is the one Where MPs Stand, Where Countries Stand and Where Councils Stand each carried, statement for
statement: ``config/settings.toml`` (or the file named by ``<PREFIX>_CONFIG``), then
``<data>/settings.local.toml`` merged over it one level deep, then keyword overrides (``section.key=value``). The
data folder is ``<PREFIX>_DATA_DIR``, else ``[paths] data_dir``, else ``data``; relative paths are relative to the
site's repository root.

A site subclasses ``Settings`` for its own accessors (and only ``Settings``: see docs/EXTENDING.md), and describes
itself once in a ``Site``. The package has no defaults for a site's limits or wording: ``require`` stops the site at
start-up, naming the key, when one is missing.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "EnvSetting",
    "Messages",
    "Settings",
    "SettingsError",
    "Site",
    "load_settings",
    "require",
    "save_local_settings",
]

LOCAL_FILE = "settings.local.toml"


class SettingsError(RuntimeError):
    """A setting the site needs is missing or wrong. The message names the section and key, and the settings file
    where whoever raised it knew which. ``problems`` is each thing wrong on its own, without the file's name: for a
    start-up check that gathers several errors into one (``briefing.desk_settings``)."""

    def __init__(self, message: str, *, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.problems: tuple[str, ...] = tuple(problems) or (message,)


@dataclass(frozen=True)
class EnvSetting:
    """One setting an environment variable may override: ``<PREFIX>_<suffix>`` sets ``[section] key``.

    ``flag`` values are true only for ``1``, ``true`` and ``yes`` (in any case); ``text`` values are stripped.
    """

    suffix: str
    section: str
    key: str
    kind: Literal["text", "flag"] = "text"


@dataclass(frozen=True)
class Site:
    """The facts about a site that are fixed in its code. Built once by the site and passed in wherever needed."""

    name: str  # "Where Councils Stand"
    package: str  # "councils"
    env_prefix: str  # "COUNCILS" (without the underscore)
    root: Path  # the repository's root: config/, data_static/ and the default data folder sit under it
    hosts: tuple[str, ...] = ()  # "wherecouncilsstand.com", "www.wherecouncilsstand.com"
    state_file: str = "state.db"  # the state database's name in the data folder ("state.sqlite" on Where MPs Stand)
    version: str = "0"  # the site's own version, for the record of each briefing
    instructions_version: str = ""  # changes when the instructions to the model change (part of the cache key)
    env_settings: tuple[EnvSetting, ...] = ()

    def env_name(self, suffix: str) -> str:
        return f"{self.env_prefix}_{suffix}"

    def env(self, suffix: str, env: Mapping[str, str] | None = None) -> str | None:
        """``<PREFIX>_<suffix>`` from the environment; an empty value counts as unset."""
        return (os.environ if env is None else env).get(self.env_name(suffix)) or None


@dataclass(frozen=True)
class Messages:
    """Every word of the briefing flow that a reader can be shown. Each site supplies all of them: the package has
    no wording of its own, so it cannot change a site's by accident."""

    too_many_requests: str  # the body of the 429
    visitor_daily_limit: str
    daily_cap: str
    monthly_cap: str
    busy_visitor: str
    busy_site: str
    sources_follow: str  # "{reason} The sources found are shown below."
    sources_only: str
    briefing_failed: str
    model_declined: str  # sent by the site's own pipeline, in its error event, when the model declines
    account_daily_limit: str | None = None  # only a site with signed-in accounts has one

    def with_sources(self, reason: str) -> str:
        return self.sources_follow.format(reason=reason)


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    data_dir: Path
    config_path: Path
    site: Site
    overrides: dict[str, Any] = field(default_factory=dict)

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def answer(self) -> dict[str, Any]:
        return self.section("answer")

    @property
    def usage(self) -> dict[str, Any]:
        return self.section("usage")

    @property
    def state_db(self) -> Path:
        return self.data_dir / self.site.state_file


def _resolve(root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def load_settings[S: Settings](cls: type[S], site: Site, config_path: str | Path | None = None,
                               env: Mapping[str, str] | None = None, **overrides: Any) -> S:
    """Read a site's settings. ``cls`` is the site's own subclass of ``Settings``."""
    path = _resolve(site.root, config_path or site.env("CONFIG", env) or Path("config") / "settings.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    data_dir = _resolve(site.root, site.env("DATA_DIR", env) or raw.get("paths", {}).get("data_dir", "data"))
    # per-installation settings (written by a site's own commands, or by hand on a server)
    local = data_dir / LOCAL_FILE
    if local.exists():
        with open(local, "rb") as fh:
            for section, values in tomllib.load(fh).items():
                raw.setdefault(section, {}).update(values)
    for setting in site.env_settings:
        # the section is there whether or not the variable is set, as it was with each site's own loader: a
        # site's accessor that reads ``raw["site"]`` finds a table, empty until something sets a key in it
        section = raw.setdefault(setting.section, {})
        value = site.env(setting.suffix, env)
        if value is not None:
            section[setting.key] = value.strip().lower() in ("1", "true", "yes") if setting.kind == "flag" \
                else value.strip()
    for dotted, value in overrides.items():
        section, _, key = dotted.partition(".")
        raw.setdefault(section, {})[key] = value
    return cls(raw=raw, data_dir=data_dir, config_path=path, site=site, overrides=overrides)


def save_local_settings(data_dir: Path, updates: Mapping[str, Mapping[str, Any]], written_by: str) -> Path:
    """Merge simple values into ``<data_dir>/settings.local.toml``, so later commands use them too.

    ``written_by`` is the command named in the file's first line (``hansard bootstrap``). Values may be booleans,
    numbers and strings; anything else is written as a string.
    """
    path = data_dir / LOCAL_FILE
    current: dict[str, dict[str, Any]] = {}
    if path.exists():
        with open(path, "rb") as fh:
            current = tomllib.load(fh)
    for section, values in updates.items():
        current.setdefault(section, {}).update(values)

    def lit(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [f"# Per-installation settings written by `{written_by}`; they override config/settings.toml."]
    for section, values in current.items():
        lines += ["", f"[{section}]", *(f"{k} = {lit(v)}" for k, v in values.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def require(settings: Settings, section: str, keys: Iterable[str]) -> dict[str, Any]:
    """The section, once every key in ``keys`` is known to be there. The package has no defaults for a site's
    limits, so a missing one stops the site at start-up rather than being guessed."""
    values = settings.section(section)
    missing = [k for k in keys if k not in values]
    if missing:
        raise SettingsError(f"{settings.config_path}: [{section}] needs " + ", ".join(missing))
    return values
