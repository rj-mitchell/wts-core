"""wts-core: the shared foundation for the Where They Stand sites.

The public interface is what this module and each submodule export in ``__all__`` (docs/adr/0007-versioning.md).
Anything else is private. The base install needs nothing but Python; ``wts_core.adapters`` holds the only modules
that import an outside library, each behind an interface in ``wts_core.ports``.
"""

from wts_core.settings import Messages, Settings, Site, load_settings

__version__ = "0.1.0.dev0"

__all__ = ["Messages", "Settings", "Site", "__version__", "load_settings"]
