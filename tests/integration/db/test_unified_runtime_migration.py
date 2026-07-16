import os
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from recipe_agent.config import get_settings

PROJECT_ROOT = Path(__file__).parents[3]
POSTGRES_PORT = 55432
POSTGRES_PASSWORD = "local-recipe-password"
POSTGRES_ADMIN_URL = f"postgresql://recipe:{POSTGRES_PASSWORD}@127.0.0.1:{POSTGRES_PORT}/postgres"


class PostgresDatabase:
    def __init__(self, database_name: str) -> None:
        self.database_name = database_name
        self.database_url = (
            f"postgresql://recipe:{POSTGRES_PASSWORD}@127.0.0.1:{POSTGRES_PORT}/{database_name}"
        )

    def upgrade(self, revision: str) -> None:
        self._migrate(command.upgrade, revision)

    def downgrade(self, revision: str) -> None:
        self._migrate(command.downgrade, revision)

    def _migrate(self, operation: Callable[[Config, str], None], revision: str) -> None:
        previous_url = os.environ.get("RECIPE_AGENT_DATABASE_URL")
        os.environ["RECIPE_AGENT_DATABASE_URL"] = self.database_url.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
        get_settings.cache_clear()
        try:
            operation(Config(PROJECT_ROOT / "alembic.ini"), revision)
        finally:
            if previous_url is None:
                os.environ.pop("RECIPE_AGENT_DATABASE_URL", None)
            else:
                os.environ["RECIPE_AGENT_DATABASE_URL"] = previous_url
            get_settings.cache_clear()

    def seed_legacy_family_recipe(self) -> tuple[UUID, UUID, UUID]:
        account_id = uuid4()
        household_id = uuid4()
        recipe_id = uuid4()
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO accounts (id, email) VALUES (%s, %s)",
                (account_id, f"{account_id}@example.com"),
            )
            connection.execute(
                "INSERT INTO households (id, owner_account_id) VALUES (%s, %s)",
                (household_id, account_id),
            )
            connection.execute(
                "INSERT INTO recipes (id, household_id) VALUES (%s, %s)",
                (recipe_id, household_id),
            )
        return account_id, household_id, recipe_id

    def seed_legacy_owned_records(self) -> dict[str, UUID]:
        account_id, household_id, recipe_id = self.seed_legacy_family_recipe()
        record_ids = {
            "account": account_id,
            "household": household_id,
            "recipe": recipe_id,
            "raw_input": uuid4(),
            "media_object": uuid4(),
            "meal_plan": uuid4(),
            "feedback_event": uuid4(),
            "recipe_rating": uuid4(),
            "conversation": uuid4(),
            "agent_run": uuid4(),
        }
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO raw_inputs (id, household_id, kind) VALUES (%s, %s, 'text')",
                (record_ids["raw_input"], household_id),
            )
            connection.execute(
                """
                INSERT INTO media_objects (id, household_id, object_key, content_type)
                VALUES (%s, %s, %s, 'image/jpeg')
                """,
                (record_ids["media_object"], household_id, str(record_ids["media_object"])),
            )
            connection.execute(
                """
                INSERT INTO meal_plans (id, household_id, week_start)
                VALUES (%s, %s, '2026-07-13')
                """,
                (record_ids["meal_plan"], household_id),
            )
            connection.execute(
                """
                INSERT INTO feedback_events (id, household_id, recipe_id, raw_text)
                VALUES (%s, %s, %s, 'legacy feedback')
                """,
                (record_ids["feedback_event"], household_id, recipe_id),
            )
            connection.execute(
                """
                INSERT INTO recipe_ratings (id, household_id, recipe_id, value)
                VALUES (%s, %s, %s, 5)
                """,
                (record_ids["recipe_rating"], household_id, recipe_id),
            )
            connection.execute(
                """
                INSERT INTO conversations (id, household_id, transport)
                VALUES (%s, %s, 'web')
                """,
                (record_ids["conversation"], household_id),
            )
            connection.execute(
                """
                INSERT INTO agent_runs (id, conversation_id, status)
                VALUES (%s, %s, 'queued')
                """,
                (record_ids["agent_run"], record_ids["conversation"]),
            )
        return record_ids

    def fetch_one(
        self, statement: str, parameters: Mapping[str, Any] | None = None
    ) -> tuple[Any, ...] | None:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute(statement, parameters).fetchone()


@pytest.fixture
def postgres_database() -> Iterator[PostgresDatabase]:
    database_name = f"recipe_migration_{uuid4().hex}"
    try:
        admin_connection = psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip(f"PostgreSQL is not available on 127.0.0.1:{POSTGRES_PORT}")

    with admin_connection:
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    database = PostgresDatabase(database_name)
    try:
        yield database
    finally:
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def test_migration_backfills_owner_membership_and_preserves_records(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0006_operations")
    account_id, family_id, recipe_id = postgres_database.seed_legacy_family_recipe()
    postgres_database.upgrade("head")

    membership = postgres_database.fetch_one(
        "SELECT account_id, household_id, role FROM family_memberships"
    )
    recipe = postgres_database.fetch_one(
        "SELECT owner_account_id, visibility FROM recipes WHERE id = %(id)s",
        {"id": recipe_id},
    )
    assert membership == (account_id, family_id, "owner")
    assert recipe == (account_id, "family")


def test_migration_backfills_all_private_owners_and_agent_run_context(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0006_operations")
    ids = postgres_database.seed_legacy_owned_records()
    postgres_database.upgrade("head")

    for table_name, id_key in (
        ("raw_inputs", "raw_input"),
        ("media_objects", "media_object"),
        ("feedback_events", "feedback_event"),
        ("recipe_ratings", "recipe_rating"),
        ("conversations", "conversation"),
    ):
        assert postgres_database.fetch_one(
            f"SELECT owner_account_id FROM {table_name} WHERE id = %(id)s",
            {"id": ids[id_key]},
        ) == (ids["account"],)

    assert postgres_database.fetch_one(
        "SELECT owner_account_id, visibility FROM meal_plans WHERE id = %(id)s",
        {"id": ids["meal_plan"]},
    ) == (ids["account"], "family")
    assert postgres_database.fetch_one(
        """
        SELECT account_id, household_id, transport, idempotency_key,
               status, request_json, response_json, error_code, started_at, completed_at
        FROM agent_runs WHERE id = %(id)s
        """,
        {"id": ids["agent_run"]},
    ) == (
        ids["account"],
        ids["household"],
        "web",
        f"legacy:{ids['agent_run']}",
        "queued",
        "{}",
        None,
        None,
        None,
        None,
    )


def test_downgrade_preserves_legacy_records(postgres_database: PostgresDatabase) -> None:
    postgres_database.upgrade("0006_operations")
    _, household_id, recipe_id = postgres_database.seed_legacy_family_recipe()
    postgres_database.upgrade("head")
    postgres_database.downgrade("0006_operations")

    assert postgres_database.fetch_one(
        "SELECT id, household_id FROM recipes WHERE id = %(id)s",
        {"id": recipe_id},
    ) == (recipe_id, household_id)
    assert (
        postgres_database.fetch_one(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'recipes' AND column_name = 'owner_account_id'
            """
        )
        is None
    )
    assert (
        postgres_database.fetch_one(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'family_memberships'
            """
        )
        is None
    )
