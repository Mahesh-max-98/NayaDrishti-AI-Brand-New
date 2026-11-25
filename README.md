# NayaDrishti AI

A phased Nepali digital newsroom project. Development is intentionally divided into nine phases, with testing and verification after each phase.

## Current phase: Phase 6 — Editorial dashboard and draft management

Phases 1–5 are implemented. Phase 5 provides an authenticated, on-demand Nepali AI draft generator. Generated drafts are saved for editorial review and are never published automatically.

## Completed Phase 3 — News source management and collection

The newsroom now includes an authenticated source manager backed by the dedicated PostgreSQL database.

Phase 3 features:
- Add RSS and Atom feed sources.
- Edit source names and feed URLs.
- Enable or disable individual sources.
- Remove a source without deleting stories already collected from it.
- Manually collect up to 50 latest entries per enabled feed.
- Track last check, last successful check, latest item count, consecutive failures and readable errors.
- Display total, enabled and healthy source counts.
- Normalize feed text and reject malformed items without article links.
- Avoid exact URL duplicates and group highly similar recent headlines under a shared story record.
- Keep original article URLs and source provenance in the database for editorial verification.
- Protect feed fetching against local/private network targets, unsafe redirects, oversized feeds and long network waits.
- Record source-management and collection activity in PostgreSQL.

Collection is available from the newsroom and automatic monitoring is configured separately. Facebook publishing remains disabled until Phase 9.

## Phase roadmap

1. Foundation — complete
2. PostgreSQL database — complete
3. News source management and collection — implemented; production collection test pending
4. News research, duplicate detection and categorization — complete
5. Nepali AI writing engine — complete
6. Editorial dashboard and draft management — next
7. Automatic news monitoring
8. Analytics and system health
9. Facebook Page integration and publishing

Each phase must be tested before the next phase begins.

## Render environment variables

Required:
- `SECRET_KEY`: session-signing secret.
- `ADMIN_PASSWORD`: admin password.
- `DATABASE_URL`: connection URL for the dedicated `nayadrishti_ai_brand_new` database. Since the web service and database are in different Render regions, use the database's external connection URL. The app enforces TLS and verifies the database name.

AI:
- `GEMINI_API_KEY`: required to generate Nepali drafts; keep it in Render only, never in GitHub or chat.
- `GEMINI_MODEL`: optional; defaults to `gemini-2.5-flash`.

Never paste passwords, API keys, or database URLs into chat or commit them to GitHub. Do not create a second `DATABASE_URL` key; edit the existing key if it needs correction.

## Admin dashboard

- Open `/admin/login` and sign in using the admin password configured in Render.
- Add a publisher name and its actual RSS or Atom feed URL.
- Use **Collect news now** to check enabled sources.
- Use **Generate Nepali draft** on a collected story to create an unpublished AI draft.
- Generated drafts are saved to the story record. Review all claims against original source links before using them.
- Review each source's health, last check, item count and error message.
- Source management and collection APIs require an authenticated admin session.

A publisher homepage URL is not necessarily an RSS feed URL. Add only feed endpoints provided by the publisher or otherwise verified.

## Health checks

- `/health` confirms that the Flask application process is responding.
- `/ready` confirms admin configuration and a working connection to the dedicated PostgreSQL database. It returns HTTP 503 if the database is missing, unreachable, or points to a different database.

## Nepali AI writing

- Uses Gemini with the `x-goog-api-key` request header; the key is not placed in request URLs or logs.
- The prompt treats publisher content as untrusted input and instructs the model not to invent names, dates, numbers, quotes, causes or outcomes.
- If only a headline is available, the engine is instructed to produce a headline-only draft.
- Output is checked for Nepali script, stripped of raw URLs and source-credit lines, and limited to ten lines / 1,200 characters.
- Draft generation is an admin-triggered action to avoid uncontrolled API usage. Generation never publishes to Facebook.

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
