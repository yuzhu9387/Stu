"""Run browser stories against an isolated, migrated PostgreSQL database and real API."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import URL

root = Path(__file__).resolve().parents[1]
admin_url = os.environ.get(
    "RECIPE_AGENT_E2E_DATABASE_ADMIN_URL", "postgresql://recipe:recipe@localhost:55433/postgres"
)
name = f"stu_e2e_{uuid4().hex}"
api_port = int(os.environ.get("RECIPE_AGENT_E2E_API_PORT", "8002"))
web_port = int(os.environ.get("RECIPE_AGENT_E2E_WEB_PORT", "3107"))
connection = psycopg.connect(admin_url, autocommit=True)
connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
params = psycopg.conninfo.conninfo_to_dict(admin_url)
params["dbname"] = name
database_url = URL.create(
    "postgresql+asyncpg",
    username=params.get("user"),
    password=params.get("password"),
    host=params.get("host", "localhost"),
    port=int(params.get("port", "5432")),
    database=name,
).render_as_string(hide_password=False)
env = {
    **os.environ,
    "RECIPE_AGENT_ENVIRONMENT": "development",
    "RECIPE_AGENT_DATABASE_URL": database_url,
    "RECIPE_AGENT_WEB_ORIGIN": f"http://localhost:{web_port}",
    "OPENAI_API_KEY": "",  # Explicitly test the honest unconfigured-provider path; no paid calls.
    "NEXT_PUBLIC_API_BASE_URL": f"http://localhost:{api_port}",
    "E2E_API_BASE_URL": f"http://localhost:{api_port}",
    "E2E_WEB_PORT": str(web_port),
    "NEXT_DIST_DIR": ".next-e2e",
}
server = None
try:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, check=True
    )
    with tempfile.TemporaryFile(mode="w+") as logs:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.e2e_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=root,
            env=env,
            stdout=logs,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if server.poll() is not None:
                logs.seek(0)
                raise RuntimeError("Test API failed to start:\n" + logs.read())
            try:
                with urllib.request.urlopen(f"http://localhost:{api_port}/health/live", timeout=1):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Test API startup timed out")
        browser_command = ["pnpm", "--dir", "web", "exec", "playwright", "test"]
        # A Rosetta Python parent otherwise launches universal Node as x64 even
        # when pnpm installed native arm64 Next.js/Chromium dependencies.
        if (
            sys.platform == "darwin"
            and subprocess.run(
                ["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True
            ).stdout.strip()
            == "1"
        ):
            browser_command = [
                "/usr/bin/arch",
                "-arm64",
                shutil.which("node") or "node",
                shutil.which("pnpm") or "pnpm",
                *browser_command[1:],
            ]
        outcome = subprocess.run(browser_command, cwd=root, env=env)
        if outcome.returncode:
            logs.seek(0)
            print(logs.read()[-6000:])
        sys.exit(outcome.returncode)
finally:
    if server is not None:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    connection.close()
