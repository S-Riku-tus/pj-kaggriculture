"""Strategy registry — auto-discovered.

Every module in this package that exposes a module-level ``STRATEGY`` (a
``Strategy`` subclass) is registered automatically, keyed by ``STRATEGY.name``.
Adding a strategy is just dropping a file here — no manual edit to this file —
so parallel experiments land without ever conflicting on the registry.
"""

from __future__ import annotations

import importlib
import pkgutil

REGISTRY: dict[str, str] = {}

for _module in pkgutil.iter_modules(__path__):
    if _module.name.startswith("_"):
        continue
    _mod = importlib.import_module(f"{__name__}.{_module.name}")
    _strategy = getattr(_mod, "STRATEGY", None)
    if _strategy is not None:
        REGISTRY[getattr(_strategy, "name", _module.name)] = f"{__name__}.{_module.name}"


def load(name):
    """Import a strategy module by its registered name and return its STRATEGY."""
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; known: {sorted(REGISTRY)}")
    return importlib.import_module(REGISTRY[name]).STRATEGY
