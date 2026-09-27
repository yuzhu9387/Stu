#!/usr/bin/env python3
"""Administrator MCP server for Stu's database: every table, any SQL.

It runs on your own computer over stdio, started by an MCP client such as
Claude Code, and is never exposed to the internet. `--target cloud` reaches
the production `stu` database through the Cloud SQL Auth Proxy with your
personal gcloud account; the connection string is read from Secret Manager
and never written to disk. `--target local` uses the Docker Compose database.

    .venv/bin/python scripts/stu_db_mcp.py --target cloud

This is full access, across every account and household. Prefer the app's own
MCP (Settings → AI Access) for ordinary kitchen changes: it validates them and
keeps the undo history.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from datetime import time as clock
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

import asyncpg

ACCOUNT = "yuzhu9387@gmail.com"
PROJECT = "leonas-friends"
INSTANCE = "leonas-friends:us-west2:avery-db"
SECRET = "stu-database-url"
LOCAL_DSN = "postgresql://recipe:recipe@localhost:55433/recipe"
TOKEN_LIFETIME = 50 * 60  # restart the proxy with a fresh token before the hour is up
DEFAULT_ROWS, MAX_ROWS = 200, 5000
PROTOCOL = "2025-03-26"

KITCHEN_NOTE = (
    " Household kitchen data is written by the app to kitchen_workspaces.state (JSON)"
    " and projected into the kitchen tables; a direct write to a projected table can be"
    " overwritten the next time the app changes that section, so change"
    " kitchen_workspaces.state as well, or use the app's MCP (kitchen_command)."
)
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tables",
        "description": "Every table in the Stu database with its approximate row count.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "describe_table",
        "description": "Columns, keys, foreign keys (with ON DELETE) and indexes of a table.",
        "inputSchema": {
            "type": "object",
            "properties": {"table": {"type": "string"}},
            "required": ["table"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query",
        "description": "Run a read-only SQL query (in a READ ONLY transaction) and return rows."
        " Use $1, $2… placeholders with params.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "params": {"type": "array"},
                "maxRows": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS},
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute",
        "description": "Run any SQL with full privileges — INSERT, UPDATE, DELETE, DDL — in one"
        " transaction that commits on success. Returns the status and any RETURNING rows."
        " Without params, several ;-separated statements may run together." + KITCHEN_NOTE,
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}, "params": {"type": "array"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]


def log(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


def gcloud(*args: str) -> str:
    result = subprocess.run(
        ["gcloud", *args, f"--account={ACCOUNT}", f"--project={PROJECT}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class Database:
    """Opens a fresh connection per call; for the cloud, keeps the proxy alive."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.proxy: subprocess.Popen[bytes] | None = None
        self.started = 0.0
        self.port = 0
        self.credentials: dict[str, str] | None = None

    async def connect(self) -> asyncpg.Connection:
        if self.target == "local":
            return await asyncpg.connect(LOCAL_DSN)
        if self.credentials is None:
            self.credentials = self._read_credentials()
        stale = time.monotonic() - self.started > TOKEN_LIFETIME
        if self.proxy is None or self.proxy.poll() is not None or stale:
            await self._start_proxy()
        return await asyncpg.connect(host="127.0.0.1", port=self.port, **self.credentials)

    @staticmethod
    def _read_credentials() -> dict[str, str]:
        url = urlsplit(gcloud("secrets", "versions", "access", "latest", f"--secret={SECRET}"))
        return {
            "user": unquote(url.username or ""),
            "password": unquote(url.password or ""),
            "database": url.path.lstrip("/"),
        }

    async def _start_proxy(self) -> None:
        self.close()
        self.port = free_port()
        # The token travels in the environment, not on the command line.
        environment = {**os.environ, "CSQL_PROXY_TOKEN": gcloud("auth", "print-access-token")}
        self.proxy = subprocess.Popen(
            ["cloud-sql-proxy", INSTANCE, "--address=127.0.0.1", f"--port={self.port}"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.started = time.monotonic()
        for _ in range(60):
            if self.proxy.poll() is not None:
                raise RuntimeError("cloud-sql-proxy exited; check `gcloud auth list`")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                await asyncio.sleep(0.25)
        raise RuntimeError("cloud-sql-proxy did not start")

    def close(self) -> None:
        if self.proxy is not None and self.proxy.poll() is None:
            self.proxy.terminate()
            try:
                self.proxy.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proxy.kill()
        self.proxy = None


def plain(value: Any) -> Any:
    if isinstance(value, (datetime, date, clock)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def rows_json(records: list[asyncpg.Record], limit: int) -> dict[str, Any]:
    shown = records[:limit]
    return {
        "columns": list(records[0].keys()) if records else [],
        "rows": [{key: plain(value) for key, value in record.items()} for record in shown],
        "rowCount": len(records),
        "truncated": len(records) > limit,
    }


async def run_tool(db: Database, name: str, args: dict[str, Any]) -> Any:
    connection = await db.connect()
    try:
        if name == "list_tables":
            records = await connection.fetch(
                "SELECT c.relname AS table, GREATEST(c.reltuples, 0)::bigint AS approx_rows"
                " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname"
            )
            return [dict(record) for record in records]
        if name == "describe_table":
            table = args["table"]
            columns = await connection.fetch(
                "SELECT column_name, data_type, is_nullable, column_default"
                " FROM information_schema.columns WHERE table_schema = 'public'"
                " AND table_name = $1 ORDER BY ordinal_position",
                table,
            )
            if not columns:
                raise ValueError(f"No table named {table}")
            constraints = await connection.fetch(
                "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint"
                " WHERE conrelid = format('public.%I', $1::text)::regclass ORDER BY conname",
                table,
            )
            indexes = await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes"
                " WHERE schemaname = 'public' AND tablename = $1 ORDER BY indexname",
                table,
            )
            return {
                "columns": [plain(dict(record)) for record in columns],
                "constraints": [dict(record) for record in constraints],
                "indexes": [dict(record) for record in indexes],
            }
        params = args.get("params") or []
        if name == "query":
            limit = min(int(args.get("maxRows") or DEFAULT_ROWS), MAX_ROWS)
            async with connection.transaction(readonly=True):
                records = await connection.fetch(args["sql"], *params)
            return rows_json(records, limit)
        if name == "execute":
            async with connection.transaction():
                if params:
                    statement = await connection.prepare(args["sql"])
                    records = await statement.fetch(*params)
                    status = statement.get_statusmsg()
                else:
                    status = await connection.execute(args["sql"])
                    records = []
            return {"status": status, **rows_json(records, DEFAULT_ROWS)}
        raise ValueError(f"Unknown tool: {name}")
    finally:
        await connection.close()


async def handle(db: Database, message: dict[str, Any]) -> dict[str, Any] | None:
    method, rpc_id = message.get("method"), message.get("id")
    if "id" not in message:
        return None  # notifications (e.g. notifications/initialized) need no answer
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": f"stu-db-{db.target}", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            data = await run_tool(db, params.get("name", ""), params.get("arguments") or {})
            text, failed = json.dumps(data, ensure_ascii=False, default=str), False
        except Exception as error:  # the error goes back to the model, not a crash
            text, failed = f"{type(error).__name__}: {error}", True
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    else:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


async def serve(target: str) -> None:
    db = Database(target)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    log(f"stu-db MCP ({target}) ready")
    try:
        while line := await reader.readline():
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                reply: dict[str, Any] | None = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            else:
                reply = await handle(db, message)
            if reply is not None:
                sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--target", choices=["cloud", "local"], default="cloud")
    asyncio.run(serve(parser.parse_args().target))
