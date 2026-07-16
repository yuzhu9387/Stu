# Family Recipe Agent

Family Recipe Agent is a Lark and Web application for importing household recipes, planning meals, and learning from cooking feedback.

The application uses a hub-and-spoke agent architecture, FastAPI, PostgreSQL, LiteLLM, a Lark international bot, and a bilingual Next.js interface. Product and engineering decisions are documented in `docs/`.

## Local development

1. Copy `.env.example` to `.env` and provide development credentials.
2. Run `make install` and `pnpm install`.
3. Start dependencies with `make services-up`.
4. Apply migrations with `.venv/bin/alembic upgrade head`.
5. Start the API with `make run-api` and the Web app with `pnpm --dir web dev`.

Run the full quality gate with `make verify`. Deployment and recovery procedures live in `docs/runbooks/`.
