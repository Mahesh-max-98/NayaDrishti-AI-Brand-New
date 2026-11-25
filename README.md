# NayaDrishti AI

A new Nepali news assistant, news collection and Facebook Page publishing project.

## Current features
- Nepali-first AI chat assistant (Gemini)
- Admin login at `/admin/login`
- Add and collect public RSS news feeds
- AI-generated Nepali draft posts with source links
- Manual Facebook Page publishing
- Optional automatic publishing, OFF by default
- Automatic mode only publishes a story when matching headlines appear in at least two configured feeds
- Publishing history and duplicate URL protection

## Required Render environment variables
Set these in the **new** Render service `nayadrishti-ai-brand-new`. Never paste secret values into chat or commit them to GitHub.

- `SECRET_KEY`: a long random session-signing secret
- `ADMIN_PASSWORD`: a strong admin password
- `GEMINI_API_KEY`: Gemini API key for chat and Nepali news drafts
- `FB_PAGE_ID`: Facebook Page ID
- `FB_PAGE_ACCESS_TOKEN`: Page access token with permission to publish Page posts
- `FB_GRAPH_VERSION`: optional; defaults to `v27.0`

For Facebook Page publishing, Meta currently documents the Page Feed endpoint and requires a Page access token plus the `pages_manage_posts` permission (and Page task access such as CREATE_CONTENT). See https://developers.facebook.com/docs/graph-api/reference/page/feed/.

## Setup
1. Add the environment variables above to the new Render service.
2. Open `/admin/login` and sign in.
3. Add trusted publishers' public RSS feed URLs.
4. Collect feeds and review the Nepali AI drafts and their source links.
5. Test one manual post only after confirming the correct Facebook Page.
6. Turn automatic publishing ON only after checking the feeds and drafts.

## Important deployment/storage notes
- Automatic publishing is OFF by default.
- Scheduled checks run every 15 minutes while the Render service is running.
- Automatic publishing requires two different configured feeds to contain matching headlines. This is a basic corroboration filter, not a guarantee that a story is true; keep reviewing sources.
- The current default SQLite database path is `/tmp/nayadrishti.db`. Render's free service filesystem is ephemeral, so feeds, drafts and history can be lost after a restart or redeploy. Configure a persistent disk or managed database before relying on long-term history or unattended operation.
- Do not publish full copyrighted articles. The app creates short summaries and links back to the original publisher.
- Never expose Page access tokens or Gemini API keys in the browser, GitHub, or chat.

## Run locally
```bash
pip install -r requirements.txt
python app.py
``

Production start:
```bash
gunicorn --workers 1 --threads 8 app:app
``
