# NayaDrishti AI

A phased Nepali digital newsroom project. Development is intentionally divided into nine phases, with testing and verification after each phase.

## Current phase: Phase 1 — Foundation

Current application components:
- Flask web application
- Responsive homepage
- AI assistant page (AI configuration is handled in a later phase)
- Admin login and protected admin routes
- Liveness endpoint: `/health`
- Configuration readiness endpoint: `/ready`
- Basic browser security headers
- Eight-hour permanent admin session lifetime

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

## Phase 1 Render configuration

Set these environment variables in the Render dashboard for the new service:

- `SECRET_KEY`: a long, randomly generated session-signing secret.
- `ADMIN_PASSWORD`: a strong, unique admin password.

Never paste either value into chat or commit them to GitHub.

The application can serve its homepage and liveness endpoint without these values, but admin login and readiness checks will remain unavailable until both are configured.

## Health checks

- `/health` confirms that the Flask application is responding.
- `/ready` confirms that the required Phase 1 admin configuration is present. It returns HTTP 503 until `SECRET_KEY` and `ADMIN_PASSWORD` are configured.

## Facebook integration

Facebook integration is reserved for Phase 9. Publishing and scheduled publishing are currently locked in the application. Do not add Facebook Page credentials or enable publishing during earlier phases.

## Hosting

- GitHub repository: `Mahesh-max-98/NayaDrishti-AI-Brand-New`
- Render service: `nayadrishti-ai-brand-new`
- Production start command: `gunicorn --workers 1 --threads 8 app:app`

## Local development

```bash
pip install -r requirements.txt
python app.py
```
