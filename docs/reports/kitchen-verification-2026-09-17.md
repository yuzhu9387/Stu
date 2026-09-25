# Kitchen workspace verification

Implemented code follows the authorized [spec](../superpowers/specs/2026-09-17-kitchen-workspace.md). This report distinguishes deterministic verification, live local HTTP checks, and unverified external services.

| Check | Result |
| --- | --- |
| Frontend full Vitest suite | 39 passed in 14 files |
| TypeScript | Passed |
| Changed frontend ESLint | Passed |
| Next.js optimized build | Passed; 18 prerendered pages, preserved dynamic legacy routes |
| Kitchen Python unit/integration suite | 44 passed |
| Broader backend regression | 280 passed, 25 skipped, one existing Lark AES fixture failure before the final preference/source tests |
| New migration SQL compilation | 0012 → head produces PostgreSQL SQL |
| Local authenticated HTTP | 11 checks passed on isolated SQLite database |
| Browser live persistence | Chinese food added via Fridge; remains after reload |
| Demo browser flow | Actual prep, stock debit, independent like, safe undo, scoped chat draft |
| Responsive drawer | 1280×900 desktop, 390×844 phone; no document overflow on phone |

The Lark failure is `tests/unit/lark/test_crypto.py::test_lark_cipher_decrypts_aes_cbc_payload`. The fixture and crypto implementation were not changed by the kitchen work; it is not counted as a passing full quality gate. Database-dependent skipped suites are not represented as passed.

The preview API runs at `127.0.0.1:8001` with `/private/tmp/stu-kitchen-browser.db`. The browser uses `http://localhost:3000` and `NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`, keeping existing port-8000 services untouched. Temporary test households contain only explicitly labeled test food. Production routes are not seeded with demo records.

The demo intentionally simulates generation and chat. Provider tests inject responses to validate structure, scope, references, allergy constraints, timing and actual image-message payloads. No real model output or deployed Friday run is claimed. MCP protocol/authentication is tested through the actual registered HTTP routes, using the existing session cookie; external OAuth/bearer client compatibility is not implemented.

Reproducible commands and operational setup are in the [runbook](../runbooks/kitchen-workspace.md). Visual comparison and remaining polish are recorded in [design QA](../../design-qa.md).

PostgreSQL verification subsequently passed in a unique temporary database: full migration to0014, table creation, concurrent first-insert retry, row-lock retry, same-revision conflict and household isolation. Only the temporary database was dropped afterward. Evidence: `docs/reports/kitchen-postgres-verification-2026-09-17.json`.
