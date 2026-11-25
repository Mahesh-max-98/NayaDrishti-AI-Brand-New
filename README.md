# NayaDrishti AI

A phased Nepali digital newsroom project. Development is intentionally divided into nine phases, with testing and verification after each phase.

## Current phase: Phase 2 — PostgreSQL database

The application now uses the dedicated PostgreSQL database named `nayadrishti_ai_brand_new` for durable newsroom storage.

Phase 2 database tables:
- `sources`: configured RSS sources and source health fields
- `stories`: collected stories, duplicate/source-match metadata and draft text
- `settings`: application settings
- `draft_revisions`: future draft version history
- `activity_logs`: newsroom activity records
- `schema_migrations`: applied database schema versions

The application verifies the target database name before creating or writing tables. This prevents accidental writes to another project’s database. PostgreSQL connections use TLS.

## Phase roadmap

1. Foundation
2. PostgreSQL database
3. News source management and collection
4. News research, duplicate detection and categorization
5. Nepali AI writing engine
6. Editorial dashboard and draft management
7. Automatic news monitoring
8. Analytics and system health
9. Facebook Page integration and publishing

Each phase must be tested before the next phase begins.

## Render environment variables

Required:
- `SECRET_KEY`: session-signing secret.
- `ADMIN_PASSWORD`: admin login password.
- `DATABASE_URL`: connection URL for the dedicated `nayadrishti_ai_brand_new` database. Since the web service and database are in different Render regions, use the database's external connection URL. The app enforces TLS and verifies the database name.

AI:
- `GEMINI_API_KEY`: optional until AI drafting is tested.
- `GEMINI_MODEL`: optional; defaults to `gemini-2.5-flash`.

Never paste passwords, API keys, or database URLs into chat or commit them to GitHub. Do not create a second `DATABASE_URL` key; edit the existing key if it needs correction.

## Health checks

- `/health` confirms that the Flask application process is responding.
- `/ready` confirms admin configuration and a working connection to the dedicated PostgreSQL database. It returns HTTP 503 if the database is missing, unreachable, or points to a different database.

## Facebook integration

Facebook integration is reserved for Phase 9. Publishing and scheduled publishing remain locked. Do not add Facebook Page credentials or enable publishing during earlier phases.

## Hosting

- GitHub repository: `Mahesh-max-98/NayaDrishti-AI-Brand-New`
- Render service: `nayadrishti-ai-brand-new`
- PostgreSQL database: `nayadrishti-ai-brand-new`
- Production start command: `gunicorn --workers 1 --threads 8 app:app`

## Local development

Set a PostgreSQL `DATABASE_URL` for a local development database, then run:

```bash
pip install -r requirements.txt
python app.py
```
