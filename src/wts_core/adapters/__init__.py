"""One module per outside tool, each behind an interface in ``wts_core.ports``.

Only modules in this package may import an outside library (``anthropic``, ``fastembed``, ``lancedb``, ``duckdb``,
``httpx``, ``numpy``, ``pyarrow``), and each imports its own when it is first used, so the base install never needs
them. ``tests/test_walls.py`` reads the imports and fails otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping

from wts_core.ports import ModelClient
from wts_core.settings import Settings, SettingsError, Site

__all__ = ["model_client"]


def model_client(settings: Settings, site: Site, env: Mapping[str, str] | None = None) -> ModelClient:
    """The client for the provider named in ``[answer] provider`` ("anthropic" when the setting is absent, as every
    site is today). Make it once and keep it for the life of the process: it remembers what the provider refused."""
    provider = str(settings.answer.get("provider", "anthropic")).strip().lower()
    if provider == "anthropic":
        from wts_core.adapters.anthropic import from_settings

        return from_settings(settings, site, env)
    raise SettingsError(f"{settings.config_path}: [answer] provider is {provider!r}; the only provider there is an "
                        "adapter for is \"anthropic\"")
