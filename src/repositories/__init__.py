"""Repository exports."""

import os
from src.repositories.base import ProductRepository
from src.repositories.sqlite_repo import SqliteRepository
from src.repositories.api_repo import ApiRepository

_sqlite_repo = SqliteRepository()
# Conectar exclusivamente a PostgreSQL (API Centralizada) con SQLite totalmente desactivado
_api_repo = ApiRepository(fallback_repo=None)


def get_repository() -> ApiRepository | SqliteRepository:
    """Get the active repository implementation (REST API or SQLite)."""
    data_source = os.getenv("DATA_SOURCE", "api").lower().strip()
    if data_source == "sqlite":
        return _sqlite_repo
    return _api_repo


def get_sqlite_repository() -> SqliteRepository:
    """Get the SQLite repository instance."""
    return _sqlite_repo


def get_api_repository() -> ApiRepository:
    """Get the REST API repository instance."""
    return _api_repo


__all__ = [
    "ProductRepository",
    "SqliteRepository",
    "ApiRepository",
    "get_repository",
    "get_sqlite_repository",
    "get_api_repository",
]
