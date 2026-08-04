from recipe_agent.infrastructure.db.migrations import to_sync_database_url


def test_postgres_migrations_use_the_declared_psycopg_driver() -> None:
    async_url = "postgresql+asyncpg://recipe:secret@localhost:55432/recipe_local"

    assert to_sync_database_url(async_url) == (
        "postgresql+psycopg://recipe:secret@localhost:55432/recipe_local"
    )


def test_sqlite_migration_url_is_unchanged() -> None:
    assert to_sync_database_url("sqlite:////tmp/recipe.db") == "sqlite:////tmp/recipe.db"
