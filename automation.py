import os
import json
import secrets
import urllib.parse
import urllib.request
import urllib.error
import re
import logging
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
        c.execute("INSERT INTO settings(key, value) VALUES('auto', '0') ON CONFLICT(key) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT(version) DO NOTHING")


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


def add(title, summary, url, source):
    if not title or not url.startswith(("http://", "https://")):
        return False
    with conn() as c:
        if c.execute("SELECT id FROM stories WHERE url=%s", (url,)).fetchone():
            return False
        rows = c.execute(
            "SELECT id,title,sources,source_count FROM stories WHERE status <> 'published' ORDER BY id DESC LIMIT 120"
        ).fetchall()
        match = None
        norm = lambda s: re.sub(r"\\W+", " ", s.lower()).strip()
        for row in rows:
            if SequenceMatcher(None, norm(title), norm(row["title"])).ratio() >= 0.86:
                match = row
                break
        if match:
            names = match["sources"] or []
            if source not in names:
                names.append(source)
            c.execute(
                "UPDATE stories SET sources=%s,source_count=%s,updated_at=NOW() WHERE id=%s",
                (Jsonb(names), len(names), match["id"])
            )
            return True
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
    text = draft(title, summary, url)
    with conn() as c:
        c.execute("UPDATE stories SET draft=%s,updated_at=NOW() WHERE id=%s", (text, sid))
    return True


def collect():
    added = 0
    with conn() as c:
        feeds = c.execute("SELECT name,url FROM sources WHERE enabled=TRUE ORDER BY name").fetchall()
    for f in feeds:
        try:
            parsed = feedparser.parse(f["url"])
            for e in parsed.entries[:20]:
                if add(
                    getattr(e, "title", "").strip(),
                    getattr(e, "summary", ""),
                    getattr(e, "link", "").strip(),
                    f["name"]
                ):
                    added += 1
            with conn() as c:
                c.execute("UPDATE sources SET last_checked=NOW(),last_success=NOW(),last_error=NULL WHERE url=%s", (f["url"],))
        except Exception as exc:
            logger.exception("RSS collection failed for a configured source.")
            with conn() as c:
                c.execute("UPDATE sources SET last_checked=NOW(),last_error=%s WHERE url=%s", (str(exc)[:500], f["url"]))
    return added


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
        feeds = c.execute("SELECT name,url FROM sources ORDER BY name").fetchall()
        rows = c.execute(
            "SELECT id,title,url,source_name,source_count,draft,status,post_id FROM stories ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return jsonify({
        "facebook": False,
        "auto": False,
        "sources": [dict(x) for x in feeds],
        "stories": [dict(x) for x in rows]
    })


@bp.post("/api/admin/sources")
@auth
def source_add():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:100]
    url = str(data.get("url", "")).strip()
    if not name or not url.startswith(("https://", "http://")):
        return jsonify({"error": "Enter a source name and valid RSS URL."}), 400
    try:
        with conn() as c:
            c.execute("INSERT INTO sources(name,url) VALUES(%s,%s)", (name, url))
    except psycopg.errors.UniqueViolation:
        return jsonify({"error": "This feed is already added."}), 409
    return jsonify({"ok": True})


@bp.post("/api/admin/collect")
@auth
def collect_now():
    return jsonify({"added": collect()})


@bp.post("/api/admin/auto")
@auth
def auto_toggle():
    return jsonify({"error": "Automatic publishing is reserved for Phase 9 and is disabled for now."}), 403


@bp.post("/api/admin/publish/<int:sid>")
@auth
def publish_now(sid):
    ok, result = publish(sid, True)
    return (jsonify({"ok": True, "post_id": result}) if ok else (jsonify({"error": result}), 400))
