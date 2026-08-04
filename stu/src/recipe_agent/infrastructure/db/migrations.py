"""Database URL normalization for synchronous Alembic migrations."""


def to_sync_database_url(database_url: str) -> str:
    """Select an explicit synchronous driver without changing non-Postgres URLs."""

    return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
