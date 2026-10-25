# DB_SQL_GEN

Text-to-SQL assistant for SFA sales data. A user asks a question in plain language. A LangGraph agent turns it into one read-only `SELECT`, runs it against the sales database, and returns a table or chart.

The product name in the web UI is **SFA SmartAnalyst**.

Python 3.11. Dependencies are locked in `pyproject.toml` and `uv.lock`.

## Run

Copy `.env` into the repo root before starting either app. Required names are listed under [Configuration](#configuration). `data/business_definitions.yaml` must exist locally. That folder is gitignored.

```bash
uv sync
```

API and web UI (docs at `/docs`, UI at `/app`, health at `/health`):

```bash
python main.py
```

The server listens on port `8688`. The systemd unit is `deploy/textsql-api.service`. Server setup is in `HOSTING_GUIDE.md`.

Tests:

```bash
pytest
```

## How a question moves

The workflow is `src/agents/orchestrator.py` (`AgentOrchestrator`). It is on when `ENABLE_PRODUCTION_GRAPH` is true (the default).

1. Load session memory and check the semantic cache.
2. Authorization guardrails. A user with no allowed rep codes is denied.
3. `supervisor` chooses the next step: clarify, chitchat, reuse the previous result, or run SQL.
4. On the same graph, SQL planning, schema retrieval, generation, validation, execution, and reflection run as their own nodes.
5. The formatter builds the answer. The result is cached and the turn is saved to memory.

Follow-up questions that only filter, sort, or aggregate the last result run against an in-memory DuckDB table named `last_result` (`src/agents/tools/local_sql_engine.py`). They go back to MySQL when the cached rows are not enough.

Every statement is checked by `src/infrastructure/db/sql_safety.py` before it reaches a database. One `SELECT` is allowed. Writes, DDL, and multi-statement scripts are rejected and must not be retried into a write.

Row scope is `RepCode IN (...)` from the signed-in user's allowed rep codes, applied in `security_policy_node`.

## Where to change things

| Change | Start here |
| --- | --- |
| Dialog routing (clarify, chitchat, follow-up, new SQL) | `src/agents/router.py`, `src/agents/orchestrator.py` |
| SQL plan, generation, execution, retry | `src/agents/orchestrator.py`, `src/agents/planner.py`, `src/agents/generator.py`, `src/agents/critic.py` |
| Prompts | `src/agents/prompts/agent_prompts.py` |
| Shared graph state | `src/agents/state.py` |
| SELECT-only policy | `src/infrastructure/db/sql_safety.py` |
| Database connection and schema reads | `src/infrastructure/db/database.py` |
| Business metric meanings | `data/business_definitions.yaml` (local only) and `src/services/knowledge/store.py` |
| HTTP API | `src/api/endpoints.py`, `src/api/routers/` |
| Request and response models | `src/api/data_models.py` |
| Browser UI served by FastAPI | `web/index.html`, `web/static/` |
| Settings | `src/config/config_management.py` |

`python main.py` starts the API and the web UI.

## API surface

Assembled in `src/api/endpoints.py`.

| Method | Path | Role |
| --- | --- | --- |
| `GET` | `/health` | Process and dependency health |
| `POST` | `/auth/phone`, `/auth/system` | Login |
| `GET` | `/auth/me` | Current user |
| `POST` | `/query` | One-shot question |
| `POST` | `/conversations`, `/conversations/stream` | New chat, optional stream |
| `POST` | `/conversations/{session_id}/follow-up` | Next turn in a session |
| `GET` | `/schema/tables`, `/schema/table/{table_name}` | Schema inspection |
| `GET` | `/knowledge/definitions` | Business definitions |
| `POST` | `/knowledge/definitions`, `/knowledge/reload` | Update or reload definitions |
| `POST` | `/examples`, `/examples/seed` | Few-shot SQL examples |
| `POST` | `/feedback` | User feedback |
| `DELETE` | `/cache` | Clear semantic cache |

## Layout

```text
main.py                 API and web UI
src/agents/             LangGraph nodes, prompts, and the local SQL tool
src/api/                FastAPI routers and the conversation service
src/services/           Auth, semantic cache, few-shot examples, business knowledge
src/infrastructure/     Config, models, and database
web/                    Static UI served at /app
data/                   Local business definitions (not in git)
scripts/                Seeding and manual checks
tests/                  pytest
deploy/                 systemd units
```

Ignored local state, do not commit and do not delete during cleanup: `data/`, `.env`, `cache/`, `database/`, `vector_store/`. Git sync notes are in `GIT_COMMANDS.md`.

## Configuration

`src/config/config_management.py` loads `.env`. These variables have no default and the app will not start without them:

- `GROQ_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `DATABASE_URI`
- `CHATBOT_AUTH_URL`, `CHATBOT_API_KEY`, `CHATBOT_BASE_URL`, `CHATBOT_SYSTEM_LOGIN_URL`
- `QDRANT_URL`, `QDRANT_API_KEY`

Defaults that change behavior:

| Variable | Default | Effect |
| --- | --- | --- |
| `ENABLE_PRODUCTION_GRAPH` | `true` | Use the production graph |
| `ENABLE_CLARIFY` | `true` | Ask a follow-up when the question is ambiguous |
| `ENABLE_TRANSFORM_PREVIOUS` | `true` | Answer from the previous result when possible |
| `ENABLE_PRE_EXEC_CRITIC` | `false` | Extra SQL review before execution |
| `ENABLE_RESULT_VERIFIER` | `true` | Check the result after execution |
| `SQL_MAX_ROWS` | `1000` | Row cap |
| `BUSINESS_DOC_YAML_PATH` | `data/business_definitions.yaml` | Metric definitions |
| `ENABLE_SEMANTIC_CACHE` | `true` | Reuse similar past questions |

## Rules for edits

- Keep generated SQL read-only. Extend `src/core/sql_safety.py` when a new statement shape appears. Do not bypass `assess_sql`.
- Keep rep-level filters on `RepCode`. Do not drop `security_policy_node` to make a query succeed.
- Business definitions stay in local `data/`. Change the YAML for metric meaning. Change Python only for how those definitions are loaded or retrieved.
- Put new HTTP routes in `src/api/routers/` and register the router in `src/api/endpoints.py`.
- Match the surrounding module style. Graph nodes return partial state dicts.
- Do not commit `.env`, `data/`, caches, or vector stores.

## Related docs

- `HOSTING_GUIDE.md` — Linux systemd hosting
- `GIT_COMMANDS.md` — branch flow, review, release, and syncing without deleting local `data/`
- `REPO_GITHUB_UPDATE.md` — update a deployed checkout
- `mysql_restore_instruction.md` — restore the MySQL source data
