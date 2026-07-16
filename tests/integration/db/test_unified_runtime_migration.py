import os
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
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


def test_family_invites_enforce_unique_codes_required_fields_and_foreign_keys(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0006_operations")
    account_id, household_id, _ = postgres_database.seed_legacy_family_recipe()
    postgres_database.upgrade("head")
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    parameters = {
        "id": uuid4(),
        "household_id": household_id,
        "account_id": account_id,
        "code_hash": "a" * 64,
        "expires_at": expires_at,
    }

    assert postgres_database.fetch_one(
        """
        INSERT INTO family_invites
            (id, household_id, created_by_account_id, code_hash, expires_at)
        VALUES (%(id)s, %(household_id)s, %(account_id)s, %(code_hash)s, %(expires_at)s)
        RETURNING code_hash, consumed_at, consumed_by_account_id, created_at IS NOT NULL
        """,
        parameters,
    ) == ("a" * 64, None, None, True)
    required_columns = postgres_database.fetch_one(
        """
        SELECT string_agg(column_name, ',' ORDER BY column_name)
        FROM information_schema.columns
        WHERE table_name = 'family_invites' AND is_nullable = 'NO'
        """
    )
    assert required_columns is not None
    assert set(required_columns[0].split(",")) == {
        "id",
        "household_id",
        "created_by_account_id",
        "code_hash",
        "expires_at",
        "created_at",
    }

    with pytest.raises(psycopg.errors.UniqueViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO family_invites
                (id, household_id, created_by_account_id, code_hash, expires_at)
            VALUES (%(id)s, %(household_id)s, %(account_id)s, %(code_hash)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4()},
        )
    with pytest.raises(psycopg.errors.NotNullViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO family_invites
                (id, household_id, created_by_account_id, code_hash, expires_at)
            VALUES (%(id)s, %(household_id)s, NULL, %(code_hash)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "code_hash": "b" * 64},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO family_invites
                (id, household_id, created_by_account_id, code_hash, expires_at)
            VALUES (%(id)s, %(household_id)s, %(account_id)s, %(code_hash)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "account_id": uuid4(), "code_hash": "c" * 64},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO family_invites
                (id, household_id, created_by_account_id, code_hash, expires_at)
            VALUES (%(id)s, %(household_id)s, %(account_id)s, %(code_hash)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "household_id": uuid4(), "code_hash": "g" * 64},
        )


def test_suggested_actions_enforce_schema_and_allow_unconsumed_rows(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0006_operations")
    ids = postgres_database.seed_legacy_owned_records()
    postgres_database.upgrade("head")
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    parameters = {
        "id": uuid4(),
        "token_hash": "d" * 64,
        "run_id": ids["agent_run"],
        "account_id": ids["account"],
        "household_id": ids["household"],
        "action_type": "create_recipe",
        "expires_at": expires_at,
    }

    assert postgres_database.fetch_one(
        """
        INSERT INTO suggested_actions
            (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
        VALUES
            (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
             %(household_id)s, %(action_type)s, %(expires_at)s)
        RETURNING arguments_json, consumed_at, consumed_by_account_id, created_at IS NOT NULL
        """,
        parameters,
    ) == ("{}", None, None, True)
    required_columns = postgres_database.fetch_one(
        """
        SELECT string_agg(column_name, ',' ORDER BY column_name)
        FROM information_schema.columns
        WHERE table_name = 'suggested_actions' AND is_nullable = 'NO'
        """
    )
    assert required_columns is not None
    assert set(required_columns[0].split(",")) == {
        "id",
        "token_hash",
        "run_id",
        "account_id",
        "household_id",
        "action_type",
        "arguments_json",
        "expires_at",
        "created_at",
        "execution_status",
        "attempt_count",
    }

    with pytest.raises(psycopg.errors.UniqueViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, %(action_type)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4()},
        )
    with pytest.raises(psycopg.errors.NotNullViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, NULL, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "token_hash": "e" * 64},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, %(action_type)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "token_hash": "f" * 64, "run_id": uuid4()},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, %(action_type)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "token_hash": "g" * 64, "account_id": uuid4()},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type, expires_at)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, %(action_type)s, %(expires_at)s)
            """,
            parameters | {"id": uuid4(), "token_hash": "h" * 64, "household_id": uuid4()},
        )


def test_live_read_migration_preserves_legacy_shares_and_adds_preferences(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0007_unified_runtime")
    account_id = uuid4()
    household_id = uuid4()
    assert postgres_database.fetch_one(
        "INSERT INTO accounts (id, email) VALUES (%(id)s, %(email)s) RETURNING id",
        {"id": account_id, "email": f"{account_id}@example.com"},
    ) == (account_id,)
    assert postgres_database.fetch_one(
        """
        INSERT INTO households (id, owner_account_id)
        VALUES (%(id)s, %(account_id)s) RETURNING id
        """,
        {"id": household_id, "account_id": account_id},
    ) == (household_id,)
    share_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    assert postgres_database.fetch_one(
        """
        INSERT INTO share_snapshots
            (id, token_hash, snapshot_json, expires_at)
        VALUES (%(id)s, %(token_hash)s, '{}', %(expires_at)s)
        RETURNING id
        """,
        {
            "id": share_id,
            "token_hash": "l" * 64,
            "expires_at": expires_at,
        },
    ) == (share_id,)

    postgres_database.upgrade("head")

    assert postgres_database.fetch_one(
        """
        SELECT owner_account_id, household_id
        FROM share_snapshots WHERE id = %(id)s
        """,
        {"id": share_id},
    ) == (None, None)
    preference_id = uuid4()
    assert postgres_database.fetch_one(
        """
        INSERT INTO dietary_preferences
            (id, owner_account_id, household_id, label)
        VALUES (%(id)s, %(account_id)s, %(household_id)s, 'vegetarian')
        RETURNING visibility, created_at IS NOT NULL
        """,
        {
            "id": preference_id,
            "account_id": account_id,
            "household_id": household_id,
        },
    ) == ("family", True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        postgres_database.fetch_one(
            """
            INSERT INTO dietary_preferences
                (id, owner_account_id, household_id, label)
            VALUES (%(id)s, %(account_id)s, %(household_id)s, 'vegetarian')
            """,
            {
                "id": uuid4(),
                "account_id": account_id,
                "household_id": household_id,
            },
        )

    postgres_database.downgrade("0007_unified_runtime")
    assert postgres_database.fetch_one(
        "SELECT id FROM share_snapshots WHERE id = %(id)s", {"id": share_id}
    ) == (share_id,)
    assert (
        postgres_database.fetch_one(
            """
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'dietary_preferences'
        """
        )
        is None
    )


def test_action_execution_audit_migration_upgrades_and_downgrades(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0008_live_read_models")

    postgres_database.upgrade("head")

    columns = postgres_database.fetch_one(
        """
        SELECT string_agg(column_name, ',' ORDER BY column_name)
        FROM information_schema.columns
        WHERE table_name = 'suggested_actions'
          AND column_name IN ('execution_status', 'result_json', 'error_code')
        """
    )
    assert columns == ("error_code,execution_status,result_json",)

    postgres_database.downgrade("0008_live_read_models")
    assert postgres_database.fetch_one(
        """
        SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'suggested_actions'
          AND column_name IN ('execution_status', 'result_json', 'error_code')
        """
    ) == (0,)


def test_durable_action_execution_migration_upgrades_and_downgrades(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_database.upgrade("0009_suggested_action_execution")
    account_id = uuid4()
    household_id = uuid4()
    conversation_id = uuid4()
    run_id = uuid4()
    executing_id = uuid4()
    share_id = uuid4()
    pending_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    assert postgres_database.fetch_one(
        "INSERT INTO accounts (id, email) VALUES (%(id)s, %(email)s) RETURNING id",
        {"id": account_id, "email": f"{account_id}@example.com"},
    ) == (account_id,)
    assert postgres_database.fetch_one(
        """
        INSERT INTO households (id, owner_account_id)
        VALUES (%(id)s, %(account_id)s) RETURNING id
        """,
        {"id": household_id, "account_id": account_id},
    ) == (household_id,)
    assert postgres_database.fetch_one(
        """
        INSERT INTO conversations
            (id, household_id, owner_account_id, transport)
        VALUES (%(id)s, %(household_id)s, %(account_id)s, 'web')
        RETURNING id
        """,
        {
            "id": conversation_id,
            "household_id": household_id,
            "account_id": account_id,
        },
    ) == (conversation_id,)
    assert postgres_database.fetch_one(
        """
        INSERT INTO agent_runs
            (id, conversation_id, account_id, household_id, transport,
             idempotency_key, status, request_json)
        VALUES
            (%(id)s, %(conversation_id)s, %(account_id)s, %(household_id)s,
             'web', 'migration-populated-0009', 'completed', '{}')
        RETURNING id
        """,
        {
            "id": run_id,
            "conversation_id": conversation_id,
            "account_id": account_id,
            "household_id": household_id,
        },
    ) == (run_id,)
    for action_id, token_hash, action_type, execution_status, result_json in (
        (executing_id, "x" * 64, "save_recipe", "executing", None),
        (
            share_id,
            "y" * 64,
            "create_share",
            "succeeded",
            '{"token":"legacy-plaintext-share-secret"}',
        ),
        (pending_id, "z" * 64, "save_recipe", "pending", None),
    ):
        assert postgres_database.fetch_one(
            """
            INSERT INTO suggested_actions
                (id, token_hash, run_id, account_id, household_id, action_type,
                 arguments_json, expires_at, consumed_at, consumed_by_account_id,
                 execution_status, result_json)
            VALUES
                (%(id)s, %(token_hash)s, %(run_id)s, %(account_id)s,
                 %(household_id)s, %(action_type)s, '{}', %(expires_at)s,
                 CASE WHEN %(execution_status)s = 'executing' THEN now() ELSE NULL END,
                 CASE WHEN %(execution_status)s = 'executing' THEN %(account_id)s ELSE NULL END,
                 %(execution_status)s, %(result_json)s)
            RETURNING id
            """,
            {
                "id": action_id,
                "token_hash": token_hash,
                "run_id": run_id,
                "account_id": account_id,
                "household_id": household_id,
                "action_type": action_type,
                "expires_at": expires_at,
                "execution_status": execution_status,
                "result_json": result_json,
            },
        ) == (action_id,)

    postgres_database.upgrade("head")

    columns = postgres_database.fetch_one(
        """
        SELECT string_agg(column_name, ',' ORDER BY column_name)
        FROM information_schema.columns
        WHERE table_name = 'suggested_actions'
          AND column_name IN ('attempt_count', 'lease_expires_at')
        """
    )
    assert columns == ("attempt_count,lease_expires_at",)
    assert postgres_database.fetch_one(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'action_mutation_receipts'
        """
    ) == ("action_mutation_receipts",)
    assert postgres_database.fetch_one(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'share_snapshots' AND column_name = 'source_action_id'
        """
    ) == ("source_action_id",)
    assert postgres_database.fetch_one(
        """
        SELECT execution_status, lease_expires_at, attempt_count,
               consumed_by_account_id, error_code
        FROM suggested_actions WHERE id = %(id)s
        """,
        {"id": executing_id},
    ) == ("failed", None, 0, account_id, "legacy_execution_unrecoverable")
    assert postgres_database.fetch_one(
        """
        SELECT count(*) FROM outbox_events
        WHERE topic = 'agent.action.requested'
        """
    ) == (0,)
    assert postgres_database.fetch_one(
        """
        SELECT execution_status, result_json, error_code
        FROM suggested_actions WHERE id = %(id)s
        """,
        {"id": share_id},
    ) == ("failed", None, "legacy_share_result_scrubbed")

    assert postgres_database.fetch_one(
        """
        UPDATE suggested_actions
        SET execution_status = 'queued'
        WHERE id = %(id)s
        RETURNING execution_status
        """,
        {"id": pending_id},
    ) == ("queued",)
    assert postgres_database.fetch_one(
        """
        UPDATE suggested_actions
        SET execution_status = 'executing', attempt_count = 1,
            lease_expires_at = now() + interval '1 minute'
        WHERE id = %(id)s
        RETURNING execution_status
        """,
        {"id": executing_id},
    ) == ("executing",)

    postgres_database.downgrade("0009_suggested_action_execution")
    assert postgres_database.fetch_one(
        """
        SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'suggested_actions'
          AND column_name IN ('attempt_count', 'lease_expires_at')
        """
    ) == (0,)
    assert postgres_database.fetch_one(
        """
        SELECT execution_status, result_json, error_code
        FROM suggested_actions WHERE id = %(id)s
        """,
        {"id": pending_id},
    ) == ("failed", None, "downgrade_incomplete_action")
    assert postgres_database.fetch_one(
        """
        SELECT execution_status, result_json, error_code
        FROM suggested_actions WHERE id = %(id)s
        """,
        {"id": executing_id},
    ) == ("failed", None, "downgrade_incomplete_action")
    assert postgres_database.fetch_one(
        "SELECT result_json FROM suggested_actions WHERE id = %(id)s",
        {"id": share_id},
    ) == (None,)
    assert postgres_database.fetch_one(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_name = 'action_mutation_receipts'
        """
    ) == (0,)
