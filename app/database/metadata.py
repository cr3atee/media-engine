from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import cast

from sqlalchemy import MetaData

from app.database.base import Base


def import_model_modules(package_name: str = "app.models") -> None:
    """Import model modules so SQLAlchemy metadata includes mapped tables."""
    import pkgutil

    package = import_module(package_name)
    package_paths = getattr(package, "__path__", None)
    if package_paths is None:
        return

    for module in pkgutil.walk_packages(
        cast(Iterable[str], package_paths),
        prefix=f"{package.__name__}.",
    ):
        import_module(module.name)


def get_metadata() -> MetaData:
    """Return SQLAlchemy metadata for the current persistence models."""
    import_model_modules()
    return Base.metadata
