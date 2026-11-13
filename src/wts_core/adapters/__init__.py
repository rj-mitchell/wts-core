"""One module per outside tool, each behind an interface in ``wts_core.ports``.

Only modules in this package may import an outside library (``anthropic``, ``fastembed``, ``lancedb``, ``duckdb``,
``httpx``, ``numpy``, ``pyarrow``), and each imports its own when it is first used, so the base install never needs
them. ``tests/test_walls.py`` reads the imports and fails otherwise.
"""
