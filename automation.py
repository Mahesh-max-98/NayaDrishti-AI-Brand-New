import os
import json
import secrets
import urllib.parse
import urllib.request
import urllib.error
import re
import logging
import socket
import ipaddress
import html
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import wraps

import feedparser
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, request, session, redirect, render_template_string, jsonify

bp = Blueprint("automation", __name__)
EXPECTED_DATABASE = "nayadrishti_ai_brand_new"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
logger = logging.getLogger(__name__)


def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    # The web service and PostgreSQL instance are in different Render regions.
    # Use the external connection URL with TLS; never log the URL or credentials.
    c = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10, sslmode="require")
    actual = c.execute("SELECT current_database() AS name").fetchone()["name"]
    if actual != EXPECTED_DATABASE:
        c.close()
        raise RuntimeError("DATABASE_URL points to a database other than the dedicated NayaDrishti database.")
    return c


def init():
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                last_checked TIMESTAMPTZ,
                last_success TIMESTAMPTZ,
                last_error TEXT,
                last_item_count INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_count INTEGER NOT NULL DEFAULT 1,
                category TEXT NOT NULL DEFAULT 'Uncategorized',
                draft TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                post_id TEXT,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                published TIMESTAMPTZ
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS draft_revisions (
                id BIGSERIAL PRIMARY KEY,
                story_id BIGINT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(story_id, version)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        c.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_item_count INTEGER NOT NULL DEFAULT 0")
        c.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0")
        c.execute("INSERT INTO settings(key, value) VALUES('auto', '0') ON CONFLICT(key) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT(version) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(2) ON CONFLICT(version) DO NOTHING")


def database_status():
    try:
        with conn() as c:
            row = c.execute("""
                SELECT current_database() AS database_name,
                       to_regclass('public.schema_migrations') IS NOT NULL AS migrations_ready,
                       to_regclass('public.sources') IS NOT NULL AS sources_ready,
                       to_regclass('public.stories') IS NOT NULL AS stories_ready,
                       to_regclass('public.settings') IS NOT NULL AS settings_ready,
                       to_regclass('public.draft_revisions') IS NOT NULL AS revisions_ready,
                       to_regclass('public.activity_logs') IS NOT NULL AS logs_ready,
                       EXISTS(SELECT 1 FROM schema_migrations WHERE version=1) AS migration_applied,
                       EXISTS(SELECT 1 FROM settings WHERE key='auto') AS default_settings_ready
            """).fetchone()
            ready = all(row[k] for k in (
                "migrations_ready", "sources_ready", "stories_ready",
                "settings_ready", "revisions_ready", "logs_ready",
                "migration_applied", "default_settings_ready"
            ))
            if not ready:
                return {"ok": False, "database": None}

            # Verify the app's real table is writable and readable, then roll
            # the test row back so readiness checks never leave test records.
            marker = "readiness-" + secrets.token_hex(12)
            c.execute("SAVEPOINT nd_readiness_test")
            inserted = c.execute("""
                INSERT INTO activity_logs(event_type,message,details)
                VALUES('readiness_test',%s,%s)
                RETURNING id
            """, (marker, Jsonb({"temporary": True}))).fetchone()
            verified = c.execute(
                "SELECT message FROM activity_logs WHERE id=%s",
                (inserted["id"],)
            ).fetchone()
            c.execute("ROLLBACK TO SAVEPOINT nd_readiness_test")
            c.execute("RELEASE SAVEPOINT nd_readiness_test")
            if not verified or verified["message"] != marker:
                return {"ok": False, "database": None}
        return {"ok": True, "database": row["database_name"]}
    except Exception:
        logger.exception("PostgreSQL readiness check failed.")
        return {"ok": False, "database": None}

def getset(k, d="0"):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=%s", (k,)).fetchone()
    return r["value"] if r else d


def setset(k, v):
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            (k, str(v))
        )


def auth(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("nd_admin"):
            return (jsonify({"error": "Sign in first."}), 401) if request.path.startswith("/api/") else redirect("/admin/login")
        return f(*a, **kw)
    return w


def draft(title, summary, url):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return ""
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = (
        "नेपाली भाषामा तथ्यमा आधारित छोटो फेसबुक समाचार पोस्ट लेख। स्रोतमा नभएको तथ्य नथप। "
        "शीर्षक र ३-५ वाक्य लेख।\nशीर्षक: " + title +
        "\nविवरण: " + (summary or "")[:4000]
    )
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 450}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            x = json.loads(r.read().decode())
        return "\n".join(
            p.get("text", "") for p in x.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        ).strip()
    except Exception:
        logger.exception("AI draft request failed.")
        return ""


def _validate_feed_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP or HTTPS RSS feed URL without embedded credentials.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local or private network feed addresses are not allowed.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
        except Exception as exc:
            raise ValueError("The feed hostname could not be resolved.") from exc
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ValueError("The feed must resolve only to public internet addresses.")
    return url


class _SafeFeedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_feed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_feed(url):
    _validate_feed_url(url)
    opener = urllib.request.build_opener(_SafeFeedRedirect())
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NayaDrishtiNewsCollector/1.0", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    )
    with opener.open(req, timeout=18) as response:
        status = getattr(response, "status", 200)
        if status < 200 or status >= 300:
            raise RuntimeError("Feed server returned HTTP " + str(status))
        payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise RuntimeError("Feed is larger than the 4 MB safety limit.")
        parsed = feedparser.parse(payload, response_headers=dict(response.headers.items()))
    if parsed.bozo and not parsed.entries:
        raise RuntimeError("The server response is not a readable RSS or Atom feed.")
    return parsed


def _plain_text(value):
    value = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\\s+", " ", html.unescape(value)).strip()


def add(title, summary, url, source):
    if not title or not url.startswith(("http://", "https://")):
        return "duplicate"
    with conn() as c:
        if c.execute("SELECT id FROM stories WHERE url=%s", (url,)).fetchone():
            return "duplicate"
        rows = c.execute(
            "SELECT id,title,sources,source_count FROM stories WHERE status <> 'published' ORDER BY id DESC LIMIT 300"
        ).fetchall()
        norm = lambda value: re.sub(r"[^\\w]+", " ", value.lower()).strip()
        match = None
        for row in rows:
            if SequenceMatcher(None, norm(title), norm(row["title"])).ratio() >= 0.88:
                match = row
                break
        if match:
            names = list(match["sources"] or [])
            if source not in names:
                names.append(source)
            c.execute(
                "UPDATE stories SET sources=%s,source_count=%s,updated_at=NOW() WHERE id=%s",
                (Jsonb(names), len(names), match["id"])
            )
            return "matched"
        row = c.execute("""
            INSERT INTO stories(title,summary,url,source_name,sources,source_count,draft,status)
            VALUES(%s,%s,%s,%s,%s,1,'','draft')
            RETURNING id
        """, (title[:400], (summary or "")[:4000], url, source, Jsonb([source]))).fetchone()
        sid = row["id"]
        c.execute(
            "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
            ("story_collected", "A story was collected from a configured source.", Jsonb({"story_id": sid, "source": source}))
        )
    generated = draft(title, summary, url)
    with conn() as c:
        c.execute("UPDATE stories SET draft=%s,updated_at=NOW() WHERE id=%s", (generated, sid))
    return "new"


def collect():
    with conn() as c:
        feeds = c.execute(
            "SELECT id,name,url FROM sources WHERE enabled=TRUE ORDER BY name"
        ).fetchall()

    totals = {"checked": 0, "new": 0, "matched": 0, "duplicates": 0, "failed": 0, "sources": []}
    for feed in feeds:
        result = {
            "source_id": feed["id"], "source": feed["name"],
            "status": "ok", "items_seen": 0, "new": 0,
            "matched": 0, "duplicates": 0, "error": None
        }
        try:
            parsed = _fetch_feed(feed["url"])
            entries = parsed.entries[:50]
            result["items_seen"] = len(entries)
            for entry in entries:
                title = _plain_text(getattr(entry, "title", ""))
                link = str(getattr(entry, "link", "") or "").strip()
                summary = _plain_text(getattr(entry, "summary", "") or getattr(entry, "description", ""))
                if not title or not link.startswith(("https://", "http://")):
                    result["duplicates"] += 1
                    continue
                outcome = add(title, summary, link, feed["name"])
                result[outcome] += 1
            with conn() as c:
                c.execute("""
                    UPDATE sources
                    SET last_checked=NOW(), last_success=NOW(), last_error=NULL,
                        last_item_count=%s, consecutive_failures=0
                    WHERE id=%s
                """, (len(entries), feed["id"]))
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)[:300]
            with conn() as c:
                c.execute("""
                    UPDATE sources
                    SET last_checked=NOW(), last_error=%s, consecutive_failures=consecutive_failures+1
                    WHERE id=%s
                """, (result["error"], feed["id"]))
            logger.exception("RSS collection failed for source id %s.", feed["id"])

        totals["checked"] += 1
        for key in ("new", "matched", "duplicates"):
            totals[key] += result[key]
        if result["status"] == "error":
            totals["failed"] += 1
        totals["sources"].append(result)

    with conn() as c:
        c.execute(
            "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
            ("collection_finished", "RSS collection run finished.", Jsonb({
                key: value for key, value in totals.items() if key != "sources"
            }))
        )
    return totals


def publish(sid, manual=False):
    # Facebook publishing is intentionally locked until Phase 9.
    return False, "Facebook publishing is disabled until Phase 9."


def cycle():
    # Scheduled collection and publishing automation are introduced in Phase 7/9.
    return


# Initialize the schema only when a DATABASE_URL is configured. A connection
# problem is reported by /ready rather than crashing the web process.
if DATABASE_URL:
    try:
        init()
    except Exception:
        logger.exception("PostgreSQL schema initialization failed.")


scheduler = BackgroundScheduler(timezone="Asia/Kathmandu")
scheduler.add_job(cycle, "interval", minutes=15, id="auto-publish", replace_existing=True, max_instances=1, coalesce=True)
if os.getenv("ADMIN_PASSWORD"):
    scheduler.start()


LOGIN = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Admin login</title><style>body{background:#0b1220;color:white;font:16px system-ui;display:grid;place-items:center;min-height:90vh}.box{background:#152238;padding:28px;border-radius:16px}input,button{padding:12px;margin:6px;border-radius:8px}</style><div class=box><h2>NayaDrishti Admin</h2><p>{{error}}</p><form method=post><input name=password type=password placeholder='Admin password' required><button>Sign in</button></form></div>"""
PANEL = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>NayaDrishti Admin</title><style>body{background:#0b1220;color:#eef;font:14px system-ui;margin:0;padding:20px;max-width:1000px;margin:auto}.card{background:#152238;border:1px solid #30425c;border-radius:14px;padding:16px;margin:12px 0}input,button{padding:10px;border-radius:8px;margin:4px}button{background:#75e0c0;border:0;font-weight:bold}a{color:#8bc4ff}.muted{color:#aab8cc}pre{white-space:pre-wrap}</style><h1>NayaDrishti AI Admin</h1><a href=/admin/logout>Sign out</a><div class=card><h3>Facebook</h3><p id=fb>Loading…</p><h3>Automatic publishing</h3><p id=auto></p><button onclick=toggle()>Toggle auto publishing</button></div><div class=card><h3>Add RSS feed</h3><input id=n placeholder='Source name'><input id=u placeholder='RSS feed URL' style='width:55%'><button onclick=add()>Add feed</button><p id=msg></p><div id=feeds></div></div><button onclick=collect()>Collect news now</button><h2>News drafts / published posts</h2><p class=muted>Auto mode and Facebook publishing are disabled until their planned phases.</p><div id=stories>Loading…</div><script>
async function api(p,b){let r=await fetch(p,{method:b?'POST':'GET',headers:b?{'Content-Type':'application/json'}:{},body:b?JSON.stringify(b):undefined}),d=await r.json();if(!r.ok)throw Error(d.error||'Failed');return d}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(){let d=await api('/api/admin/status');fb.textContent='Facebook integration reserved for Phase 9';auto.textContent='OFF — publishing locked';feeds.innerHTML=d.sources.map(s=>'<p>'+esc(s.name)+' · '+esc(s.url)+'</p>').join('')||'No RSS feeds added';stories.innerHTML=d.stories.map(s=>'<div class=card><h3>'+esc(s.title)+'</h3><p class=muted>'+esc(s.source_name)+' · '+s.source_count+' feed match(es) · '+esc(s.status)+'</p><pre>'+esc(s.draft||'AI draft not available.')+'</pre><a href="'+esc(s.url)+'" target=_blank rel=noopener>Original source</a></div>').join('')||'No news yet.'}
async function add(){try{await api('/api/admin/sources',{name:n.value,url:u.value});msg.textContent='Feed added';n.value='';u.value='';load()}catch(e){msg.textContent=e.message}}
async function collect(){try{let d=await api('/api/admin/collect',{});alert('New or updated stories: '+d.added);load()}catch(e){alert(e.message)}}
async function toggle(){alert('Automatic publishing is disabled until Phase 9.')}
load()</script>"""


@bp.get("/admin/login")
def login():
    missing = not os.getenv("ADMIN_PASSWORD") or not os.getenv("SECRET_KEY")
    message = "Admin login is not configured. Add ADMIN_PASSWORD and SECRET_KEY in Render." if missing else ""
    return render_template_string(LOGIN, error=message)


@bp.post("/admin/login")
def login_post():
    password = os.getenv("ADMIN_PASSWORD", "")
    secret = os.getenv("SECRET_KEY", "")
    if password and secret and secrets.compare_digest(request.form.get("password", ""), password):
        session.clear()
        session.permanent = True
        session["nd_admin"] = True
        return redirect("/admin")
    return render_template_string(LOGIN, error="Incorrect password or admin is not configured."), 401


@bp.get("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


@bp.get("/admin")
@auth
def panel():
    return render_template_string(PANEL)


@bp.get("/api/admin/status")
@auth
def status():
    with conn() as c:
        feeds = c.execute("""
            SELECT id,name,url,enabled,last_checked,last_success,last_error,
                   last_item_count,consecutive_failures
            FROM sources ORDER BY name
        """).fetchall()
        rows = c.execute(
            "SELECT id,title,summary,url,source_name,source_count,draft,status,post_id FROM stories ORDER BY id DESC LIMIT 50"
        ).fetchall()
        summary = c.execute("""
            SELECT
              COUNT(*)::int AS total_sources,
              COUNT(*) FILTER (WHERE enabled)::int AS enabled_sources,
              COUNT(*) FILTER (WHERE enabled AND last_success IS NOT NULL AND last_error IS NULL)::int AS healthy_sources
            FROM sources
        """).fetchone()
        story_count = c.execute("SELECT COUNT(*)::int AS count FROM stories").fetchone()["count"]
    return jsonify({
        "facebook": False,
        "auto": False,
        "summary": {**dict(summary), "stories": story_count},
        "sources": [dict(x) for x in feeds],
        "stories": [dict(x) for x in rows]
    })


def _validate_feed_url_syntax(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a valid public HTTP or HTTPS RSS / Atom feed URL.")


@bp.post("/api/admin/sources")
@auth
def source_add():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:100]
    url = str(data.get("url", "")).strip()
    try:
        _validate_feed_url_syntax(url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not name:
        return jsonify({"error": "Enter a source name."}), 400
    try:
        with conn() as c:
            c.execute("INSERT INTO sources(name,url) VALUES(%s,%s)", (name, url))
            c.execute(
                "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
                ("source_added", "An RSS source was added.", Jsonb({"source_name": name}))
            )
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "This feed URL is already registered."}), 409
    return jsonify({"ok": True})


@bp.patch("/api/admin/sources/<int:sid>")
@auth
def source_update(sid):
    data = request.get_json(silent=True) or {}
    allowed = {"name", "url", "enabled"}
    if not data or not set(data).issubset(allowed):
        return jsonify({"error": "Only source name, feed URL or enabled status can be changed."}), 400
    with conn() as c:
        current = c.execute("SELECT id,name,url,enabled FROM sources WHERE id=%s", (sid,)).fetchone()
    if not current:
        return jsonify({"error": "Source not found."}), 404
    name = str(data.get("name", current["name"])).strip()[:100]
    url = str(data.get("url", current["url"])).strip()
    enabled = data.get("enabled", current["enabled"])
    if not name:
        return jsonify({"error": "Source name cannot be empty."}), 400
    if not isinstance(enabled, bool):
        return jsonify({"error": "Enabled must be true or false."}), 400
    try:
        _validate_feed_url_syntax(url)
        with conn() as c:
            c.execute("""
                UPDATE sources
                SET name=%s,url=%s,enabled=%s,
                    last_checked=CASE WHEN url<>%s THEN NULL ELSE last_checked END,
                    last_success=CASE WHEN url<>%s THEN NULL ELSE last_success END,
                    last_error=CASE WHEN url<>%s THEN NULL ELSE last_error END,
                    last_item_count=CASE WHEN url<>%s THEN 0 ELSE last_item_count END,
                    consecutive_failures=CASE WHEN url<>%s THEN 0 ELSE consecutive_failures END
                WHERE id=%s
            """, (name,url,enabled,url,url,url,url,url,sid))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "Another source already uses this feed URL."}), 409
    return jsonify({"ok": True})


@bp.delete("/api/admin/sources/<int:sid>")
@auth
def source_delete(sid):
    with conn() as c:
        row = c.execute("SELECT name FROM sources WHERE id=%s", (sid,)).fetchone()
        if not row:
            return jsonify({"error": "Source not found."}), 404
        c.execute("DELETE FROM sources WHERE id=%s", (sid,))
        c.execute(
            "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
            ("source_removed", "An RSS source was removed.", Jsonb({"source_name": row["name"]}))
        )
    return jsonify({"ok": True})


@bp.post("/api/admin/collect")
@auth
def collect_now():
    return jsonify(collect())

@bp.post("/api/admin/auto")
@auth
def auto_toggle():
    return jsonify({"error": "Automatic publishing is reserved for Phase 9 and is disabled for now."}), 403


@bp.post("/api/admin/publish/<int:sid>")
@auth
def publish_now(sid):
    ok, result = publish(sid, True)
    return (jsonify({"ok": True, "post_id": result}) if ok else (jsonify({"error": result}), 400))
