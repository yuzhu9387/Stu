# Family Recipe Agent

Family Recipe Agent is a Lark and Web application for importing household recipes, planning meals, and learning from cooking feedback.

The application uses a hub-and-spoke agent architecture, FastAPI, PostgreSQL, LiteLLM, a Lark international bot, and a bilingual Next.js interface. Product and engineering decisions are documented in `docs/`.

## Local development

1. Copy `.env.example` to `.env` and provide development credentials.
2. Run `make install` and `pnpm install`.
3. Run `make local-up` to start migrations, PostgreSQL, Redis, MinIO, API, workers, and Web.
4. Open <http://127.0.0.1:3000/chat>.

Run the full quality gate with `make verify`. Deployment and recovery procedures live in `docs/runbooks/`.
The complete local Web/Lark test sequence is in
[`docs/runbooks/local-end-to-end.md`](docs/runbooks/local-end-to-end.md).
