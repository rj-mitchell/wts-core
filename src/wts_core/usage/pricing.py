"""What a model call costs: a site's prices, read from its settings, and the one cost formula.

A site's prices are its ``[usage]`` section as it stands today: four base figures (``price_input_per_mtok``,
``price_output_per_mtok``, ``price_cache_read_per_mtok``, ``cache_write_multiplier``) and, under
``[usage.models."<name>"]``, figures laid over them for any model whose id equals the name or starts with it. The
first matching name wins, in the order the settings file gives them.

The package has no prices of its own. Each site's copy fell back to figures in its code when a key was missing
(4.0 and 20.0 on Where MPs Stand and Where Countries Stand, 2.0 and 10.0 on Where Councils Stand); here a missing
base price stops the site at start-up, naming the key.

A model that matches no entry is still costed at the base prices, as today: on every site the base prices *are* a
real model's (the briefing model's on Where Countries Stand and Where Councils Stand; a larger model's on Where
MPs Stand, with the briefing model as an entry). ``PriceTable.require`` is the start-up check that a site which
wants every model to have an entry of its own can ask for.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wts_core.ports import Price, Pricing, UnknownModel, Usage
from wts_core.settings import SettingsError

__all__ = ["PriceTable"]

# the settings keys, in the order of ``Price``'s fields
KEYS = ("price_input_per_mtok", "price_output_per_mtok", "price_cache_read_per_mtok", "cache_write_multiplier")
# an optional fifth, for a site that turns the one-hour cache on: without it, ``Price``'s own figure stands
LONG = "cache_write_long_multiplier"


def _price(section: str, laid: Mapping[str, float], *given: Mapping[str, Any]) -> Price:
    long = next((_number(section, LONG, g[LONG]) for g in reversed(given) if LONG in g), None)
    price = Price(*(laid[k] for k in KEYS))
    return price if long is None else Price(price.input, price.output, price.cache_read,
                                            price.cache_write_multiplier, long)


def _number(section: str, key: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"[{section}] {key} must be a number, not {value!r}") from None


@dataclass(frozen=True)
class PriceTable:
    """A site's prices (``ports.Pricing``): the base prices, and the models that have their own."""

    base: Price
    models: tuple[tuple[str, Price], ...] = ()

    @classmethod
    def from_settings(cls, usage: Mapping[str, Any], *, section: str = "usage") -> PriceTable:
        """Read the prices from a site's ``[usage]`` section (``settings.usage``). ``section`` is only how the
        section is named in an error, for a site that keeps its prices under another name."""
        missing = [k for k in KEYS if k not in usage]
        if missing:
            raise SettingsError(f"[{section}] needs " + ", ".join(missing) + ": the package has no prices of its own")
        base = {k: _number(section, k, usage[k]) for k in KEYS}
        per_model = usage.get("models") or {}
        if not isinstance(per_model, Mapping):
            raise SettingsError(f"[{section}] models must be tables of prices, one for each model")
        models: list[tuple[str, Price]] = []
        for name, own in per_model.items():
            where = f'{section}.models."{name}"'
            if not isinstance(own, Mapping):
                raise SettingsError(f"[{where}] must be a table of prices")
            laid = {**base, **{k: _number(where, k, own[k]) for k in KEYS if k in own}}
            models.append((str(name), _price(where, laid, usage, own)))
        return cls(base=_price(section, base, usage), models=tuple(models))

    def _entry(self, model: str | None) -> Price | None:
        for name, price in self.models:
            if model and (model == name or model.startswith(name)):
                return price
        return None

    def price_for(self, model: str | None) -> Price:
        """The prices for a model: its own entry's, or the base prices when it has none (or there is no model)."""
        return self._entry(model) or self.base

    def cost(self, usage: Usage | None, model: str | None) -> float:
        """Cost of one call in US dollars, rounded to six places. Cache writes cost the input price times the
        multiplier (the one-hour cache's own multiplier for those written to it); cache reads are priced
        separately; each token is priced once."""
        if usage is None:
            return 0.0
        p = self.price_for(model)
        return round(
            usage.input_uncached / 1e6 * p.input
            + (usage.cache_write - usage.cache_write_long) / 1e6 * p.input * p.cache_write_multiplier
            + usage.cache_write_long / 1e6 * p.input * p.cache_write_long_multiplier
            + usage.output / 1e6 * p.output
            + usage.cache_read / 1e6 * p.cache_read,
            6,
        )

    def require(self, models: Iterable[str | None], *, base_counts: bool) -> None:
        """The start-up check: every model the site's settings name must have a price.

        ``base_counts`` says whether the base prices are an entry: ``True`` is today's rule on every site (a model
        with no entry of its own takes the base prices, so nothing is unknown); ``False`` is strict pricing, where
        each model must equal or start with a name under ``[usage.models]``, and one that doesn't raises
        ``ports.UnknownModel`` rather than being costed at another model's prices. Models that are not set
        (``None`` or empty) are passed over.
        """
        if base_counts:
            return
        unknown = sorted({m for m in models if m and self._entry(m) is None})
        if unknown:
            raise UnknownModel(
                "no price for " + ", ".join(unknown) + ': add [usage.models."<name>"] with its prices to the '
                "site's settings (known: " + (", ".join(name for name, _ in self.models) or "none") + ")")

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_pricing(x: PriceTable) -> Pricing:
        return x
