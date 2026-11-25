import os
import json
import secrets
import urllib.parse
import urllib.request
import urllib.error
import re
import hashlib
import logging
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import html
from html.parser import HTMLParser
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


# RSS feeds are used where available. For outlets without a verified feed,
# the collector reads the public homepage and extracts same-site article links.
DEFAULT_SOURCES = [
    ("RONB / Routine of Nepal Banda", "https://www.youtube.com/@RoutineofNepalBanda"),
    ("BBC Nepali", "https://www.bbc.com/nepali"),
    ("Onlinekhabar", "https://www.onlinekhabar.com/feed"),
    ("OK Khabar", "https://okkhabar.com/"),
    ("Laliguras Media Network", "https://www.laligurash.com/"),
    ("Troll Cricket Nepal", "https://trollcricketnepal.com/"),
    ("eKantipur / Kantipur", "https://ekantipur.com/"),
    ("Ratopati", "https://www.ratopati.com/feed"),
    ("Annapurna Post", "https://annapurnapost.com/"),
    ("Setopati", "https://www.setopati.com/feed"),
    ("Nagarik News", "https://nagariknews.nagariknetwork.com/feed"),
    ("Gorkhapatra", "https://gorkhapatraonline.com/rss"),
    ("Ujyaalo Online", "https://www.ujyaaloonline.com/"),
    ("Thaha Khabar", "https://www.thahakhabar.com/"),
    ("Nepal Samaya", "https://nepalsamaya.com/feed"),
    ("NEB Official Notices", "https://neb.gov.np/"),
    ("Ministry of Education, Science and Technology", "https://www.moest.gov.np/"),
    ("Artha Sarokar", "https://arthasarokar.com/feed"),
    ("Rajdhani Daily", "https://rajdhanidaily.com/feed"),
    ("News of Nepal", "https://newsofnepal.com/feed"),
    ("Curriculum Development Centre", "https://www.moecdc.gov.np/"),
    ("The Rising Nepal (Government-owned)", "https://risingnepaldaily.com/"),
    ("Khabarhub", "https://www.khabarhub.com/feed/"),
    ("Nepal Press", "https://nepalpress.com/"),
    ("myRepublica", "https://myrepublica.nagariknetwork.com/"),
]


def seed_default_sources():
    """Install known public Nepal-news RSS feeds without admin data entry."""
    with conn() as c:
        # Remove duplicate URL variants so each publisher has one source row.
        for name, keep_url, duplicate_urls in (
            ("Laliguras Media Network", "https://www.laligurash.com/", ["https://english.laligurash.com/"]),
            ("Nagarik News", "https://nagariknews.nagariknetwork.com/feed", ["https://nagariknews.nagariknetwork/feed", "https://nagariknews.nagariknetwork.com/", "https://nagariknews.nagariknetwork.com.com/feed"]),
            ("RONB / Routine of Nepal Banda", "https://www.youtube.com/@RoutineofNepalBanda", ["https://www.youtube.com/feeds/videos.xml?channel_id=UC2rariKHGBaLf0qmhWQv3KQ", "https://ronbpost.com/", "https://www.ronbpost.com/"]),
            ("Khabarhub", "https://www.khabarhub.com/feed/", ["https://khabarhub.com/"]),
            ("Nepal Samaya", "https://nepalsamaya.com/feed", ["https://nepalsamaya.com/"]),
            ("NEB Official Notices", "https://neb.gov.np/", ["https://neb.gov.np/news-notices"]),
            ("Thaha Khabar", "https://www.thahakhabar.com/", ["https://thahakhabar.com/rss/", "https://thahakhabar.com/"]),
            ("Ujyaalo Online", "https://www.ujyaaloonline.com/", ["https://ujyaaloonline.com/rss", "https://www.ujyaaloonline.com/rss"]),
            ("Ministry of Education, Science and Technology", "https://www.moest.gov.np/", ["https://nepal.gov.np/"]),
            ("Curriculum Development Centre", "https://www.moecdc.gov.np/", ["https://techmandu.com/feed"]),
        ):
            for duplicate_url in duplicate_urls:
                c.execute("DELETE FROM sources WHERE url=%s AND EXISTS (SELECT 1 FROM sources WHERE url=%s)", (duplicate_url, keep_url))
                c.execute(
                    "UPDATE sources SET name=%s,url=%s,last_checked=NULL,last_success=NULL,last_error=NULL,last_item_count=0,consecutive_failures=0 WHERE url=%s AND NOT EXISTS (SELECT 1 FROM sources WHERE url=%s)",
                    (name, keep_url, duplicate_url, keep_url)
                )
        for name, url in DEFAULT_SOURCES:
            c.execute(
                "INSERT INTO sources(name,url) VALUES(%s,%s) ON CONFLICT(url) DO UPDATE SET name=EXCLUDED.name",
                (name, url)
            )


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
            CREATE TABLE IF NOT EXISTS story_sources (
                id BIGSERIAL PRIMARY KEY,
                story_id BIGINT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                article_url TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TIMESTAMPTZ,
                collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(story_id, article_url)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_story_sources_story ON story_sources(story_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_story_sources_publisher ON story_sources(source_name)")
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
        c.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ")
        c.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS research_flags JSONB NOT NULL DEFAULT '[]'::jsonb")
        c.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS evidence_status TEXT NOT NULL DEFAULT 'single_source'")
        c.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS is_breaking_candidate BOOLEAN NOT NULL DEFAULT FALSE")
        c.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS duplicate_group_key TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_stories_category_created ON stories(category, created DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_stories_published_at ON stories(published_at DESC)")
        c.execute("INSERT INTO settings(key, value) VALUES('auto', '0') ON CONFLICT(key) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT(version) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(2) ON CONFLICT(version) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(3) ON CONFLICT(version) DO NOTHING")
        c.execute("INSERT INTO schema_migrations(version) VALUES(4) ON CONFLICT(version) DO NOTHING")


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
                       EXISTS(SELECT 1 FROM schema_migrations WHERE version=2) AS source_migration_ready,
                       EXISTS(SELECT 1 FROM schema_migrations WHERE version=3) AS research_migration_ready,
                       EXISTS(SELECT 1 FROM schema_migrations WHERE version=4) AS provenance_migration_ready,
                       (SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='sources'
                        AND column_name IN ('last_item_count','consecutive_failures'))=2 AS source_health_fields_ready,
                       EXISTS(SELECT 1 FROM settings WHERE key='auto') AS default_settings_ready,
                       (SELECT COUNT(*)::int FROM sources) AS source_count
            """).fetchone()
            ready = all(row[k] for k in (
                "migrations_ready", "sources_ready", "stories_ready",
                "settings_ready", "revisions_ready", "logs_ready",
                "migration_applied", "source_migration_ready", "research_migration_ready", "provenance_migration_ready",
                "source_health_fields_ready", "default_settings_ready"
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
        return {"ok": True, "database": row["database_name"], "sources": row["source_count"]}
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


class _FeedDiscoveryParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.feeds = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        item = {str(k).lower(): (v or "") for k, v in attrs}
        rel = item.get("rel", "").lower().split()
        typ = item.get("type", "").lower()
        href = item.get("href", "").strip()
        if "alternate" in rel and href and ("rss" in typ or "atom" in typ or "xml" in typ):
            self.feeds.append(urllib.parse.urljoin(self.base_url, href))


class _HomepageLinks(HTMLParser):
    """Extract article-like same-site links from public HTML pages."""
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.host = (urllib.parse.urlsplit(base_url).hostname or "").lower()
        self.root_host = ".".join(self.host.split(".")[-2:])
        self.current = None
        self.entries = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.current = {"href": urllib.parse.urljoin(self.base_url, href), "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag != "a" or self.current is None:
            return
        title = _plain_text(" ".join(self.current["text"]))
        link = self.current["href"]
        self.current = None
        parsed = urllib.parse.urlsplit(link)
        link_host = (parsed.hostname or "").lower()
        same_site = link_host == self.host or link_host.endswith("." + self.root_host) or self.host.endswith("." + link_host)
        if (len(title) < 12 or len(title) > 240 or parsed.scheme not in ("http", "https")
                or not same_site or link in self.seen):
            return
        if any(x in parsed.path.lower() for x in ("/category/", "/tag/", "/author/", "/login", "/contact", "/about")):
            return
        self.seen.add(link)
        self.entries.append({"title": title, "link": link, "summary": ""})


def _fetch_feed(url):
    parsed_url = urllib.parse.urlsplit(url)
    base = urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, "/", "", ""))
    path = (parsed_url.path or "/").lower()
    # A configured RSS/Atom endpoint should be tried directly, not followed
    # by six unrelated paths on the same host.
    is_feed_path = (
        path.endswith(("/feed", "/feed/", "/rss", "/rss/"))
        or path.endswith((".xml", ".atom"))
    )
    candidates = [url]
    if not is_feed_path:
        for fallback_path in ("/feed", "/rss", "/rss.xml"):
            candidate = urllib.parse.urljoin(base, fallback_path.lstrip("/"))
            if candidate not in candidates:
                candidates.append(candidate)

    last_error = None
    reachable_html = False
    for candidate in candidates:
        try:
            _validate_feed_url(candidate)
            opener = urllib.request.build_opener(_SafeFeedRedirect())
            req = urllib.request.Request(
                candidate,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
                    "Accept-Language": "ne-NP,ne;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Cache-Control": "no-cache"
                }
            )
            # Keep each source check bounded so a slow publisher cannot hold
            # the whole 25-source collection cycle for several minutes.
            with opener.open(req, timeout=8) as response:
                status = getattr(response, "status", 200)
                if status < 200 or status >= 300:
                    raise RuntimeError("Source server returned HTTP " + str(status))
                payload = response.read(4 * 1024 * 1024 + 1)
                if len(payload) > 4 * 1024 * 1024:
                    raise RuntimeError("Source page is larger than the 4 MB safety limit.")
                headers = dict(response.headers.items())
                final_url = response.geturl()
            parsed = feedparser.parse(payload, response_headers=headers)
            if parsed.entries:
                return parsed

            text_payload = payload.decode("utf-8", errors="replace")
            content_type = headers.get("Content-Type", "").lower()
            if "text/html" in content_type or b"<html" in payload[:1000].lower():
                reachable_html = True
                discovery = _FeedDiscoveryParser(final_url)
                discovery.feed(text_payload)
                for feed_url in discovery.feeds:
                    if feed_url == candidate:
                        continue
                    try:
                        _validate_feed_url(feed_url)
                        feed_req = urllib.request.Request(feed_url, headers={
                            "User-Agent": "Mozilla/5.0 (compatible; NayaDrishtiNewsCollector/1.0)",
                            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
                        })
                        with opener.open(feed_req, timeout=8) as feed_response:
                            feed_payload = feed_response.read(4 * 1024 * 1024 + 1)
                            if len(feed_payload) > 4 * 1024 * 1024:
                                continue
                            discovered = feedparser.parse(
                                feed_payload,
                                response_headers=dict(feed_response.headers.items())
                            )
                        if discovered.entries:
                            return discovered
                    except Exception as exc:
                        last_error = exc

                parser = _HomepageLinks(final_url)
                parser.feed(text_payload)
                if parser.entries:
                    class _Result:
                        entries = parser.entries
                    return _Result()
            last_error = RuntimeError("The source is reachable but no readable headlines were found.")
        except Exception as exc:
            last_error = exc
            continue

    # HTTP 200 HTML means the publisher is reachable even if its page exposes
    # no article links our generic parser can read. The dashboard must show
    # this as connected-without-items, not pretend news was collected.
    if reachable_html:
        class _EmptyResult:
            entries = []
        return _EmptyResult()
    if last_error:
        raise last_error
    raise RuntimeError("No usable feed endpoint was found for this publisher.")

def _plain_text(value):
    value = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _research_category(title, summary=""):
    text_value = (str(title or "") + " " + str(summary or "")).lower()
    rules = [
        ("Politics", ["राजनीति", "सरकार", "मन्त्रिपरिषद", "मन्त्री", "संसद", "निर्वाचन", "प्रधानमन्त्री", "politic", "government", "parliament", "election"]),
        ("National", ["नेपाल", "नेपाली", "राष्ट्रिय", "देशभर", "काठमाडौं", "nepal", "national"]),
        ("International", ["अन्तर्राष्ट्रिय", "विदेश", "भारत", "चीन", "अमेरिका", "विश्व", "international", "world", "global"]),
        ("Economy", ["अर्थतन्त्र", "आर्थिक", "बजेट", "बैंक", "शेयर", "व्यापार", "महँगी", "economy", "business", "market", "bank", "finance"]),
        ("Sports", ["खेलकुद", "क्रिकेट", "फुटबल", "खेल", "विश्वकप", "league", "cricket", "football", "sports", "match"]),
        ("Education", ["शिक्षा", "विद्यालय", "कलेज", "विश्वविद्यालय", "परीक्षा", "एसईई", "शिक्षक", "education", "school", "college", "exam", "university"]),
        ("Technology", ["प्रविधि", "कम्प्युटर", "मोबाइल", "इन्टरनेट", "एआई", "सफ्टवेयर", "technology", "tech", "software", "internet", "ai"]),
        ("Health", ["स्वास्थ्य", "अस्पताल", "चिकित्सा", "रोग", "औषधि", "health", "hospital", "medical", "disease"]),
        ("Entertainment", ["मनोरञ्जन", "चलचित्र", "फिल्म", "सिनेमा", "कलाकार", "संगीत", "entertainment", "movie", "film", "music"]),
        ("Disaster & Weather", ["मौसम", "वर्षा", "बाढी", "पहिरो", "भूकम्प", "आगलागी", "weather", "flood", "landslide", "earthquake", "storm"]),
        ("Crime & Security", ["प्रहरी", "अपराध", "गिरफ्तार", "दुर्घटना", "सुरक्षा", "police", "crime", "arrest", "accident", "security"]),
    ]
    for category, keywords in rules:
        if any(word in text_value for word in keywords):
            return category
    return "Other"


def _normalized_title(value):
    value = str(value or "").lower()
    value = re.sub(r"[^\w\u0900-\u097f]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _title_similarity(left, right):
    a, b = _normalized_title(left), _normalized_title(right)
    if not a or not b:
        return 0.0
    sequence_score = SequenceMatcher(None, a, b).ratio()
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    return max(sequence_score, overlap)


def _published_datetime(entry):
    value = entry.get("published_parsed") or entry.get("updated_parsed")
    if value:
        try:
            return datetime(*value[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    raw = entry.get("published") or entry.get("updated") or ""
    if raw:
        try:
            parsed = feedparser._parse_date(raw)
            if parsed:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _research_metadata(source_names, published_at, created_at=None, summary=""):
    now = datetime.now(timezone.utc)
    flags = []
    if published_at is None:
        flags.append("publication_time_unknown")
    elif (now - published_at).total_seconds() > 48 * 3600:
        flags.append("possibly_old_news")
    unique_sources = len(set(source_names or []))
    if unique_sources >= 2:
        flags.append("similar_headline_seen_in_multiple_sources")
    if not str(summary or "").strip():
        flags.append("headline_only_no_article_summary")
    # Breaking is only a candidate when several publishers and a reliable
    # publication timestamp are present; it always needs human verification.
    breaking = unique_sources >= 3 and published_at is not None and 0 <= (now - published_at).total_seconds() <= 6 * 3600
    if breaking:
        flags.append("breaking_candidate_requires_editorial_verification")
    if unique_sources >= 2:
        evidence = "multiple_source_headline_match_only"
    else:
        evidence = "single_source_with_summary" if str(summary or "").strip() else "headline_only_single_source"
    return flags, evidence, breaking


def _record_story_source(c, story_id, source, title, summary, url, published_at):
    c.execute(
        """INSERT INTO story_sources(story_id,source_name,article_url,title,summary,published_at)
           VALUES(%s,%s,%s,%s,%s,%s)
           ON CONFLICT(story_id,article_url) DO UPDATE SET
             source_name=EXCLUDED.source_name,
             title=EXCLUDED.title,
             summary=EXCLUDED.summary,
             published_at=COALESCE(story_sources.published_at,EXCLUDED.published_at)""",
        (story_id, source, url, title[:400], (summary or "")[:4000], published_at)
    )


def _backfill_research_fields():
    # One set-based UPDATE avoids hundreds of round trips to the remote database
    # during startup and keeps the web service responsive.
    with conn() as c:
        c.execute("""
            INSERT INTO story_sources(story_id,source_name,article_url,title,summary,published_at)
            SELECT id,source_name,url,title,summary,published_at FROM stories
            ON CONFLICT(story_id,article_url) DO NOTHING
        """)
        c.execute("""
            UPDATE stories
            SET category = CASE
                WHEN (title || ' ' || summary) ~* '(राजनीति|सरकार|मन्त्री|संसद|निर्वाचन|प्रधानमन्त्री|politic|government|parliament|election)' THEN 'Politics'
                WHEN (title || ' ' || summary) ~* '(अन्तर्राष्ट्रिय|विदेश|भारत|चीन|अमेरिका|विश्व|international|world|global)' THEN 'International'
                WHEN (title || ' ' || summary) ~* '(अर्थतन्त्र|आर्थिक|बजेट|बैंक|शेयर|व्यापार|महँगी|economy|business|market|finance)' THEN 'Economy'
                WHEN (title || ' ' || summary) ~* '(खेलकुद|क्रिकेट|फुटबल|खेल|विश्वकप|league|cricket|football|sports|match)' THEN 'Sports'
                WHEN (title || ' ' || summary) ~* '(शिक्षा|विद्यालय|कलेज|विश्वविद्यालय|परीक्षा|एसईई|शिक्षक|education|school|college|exam|university)' THEN 'Education'
                WHEN (title || ' ' || summary) ~* '(प्रविधि|कम्प्युटर|मोबाइल|इन्टरनेट|एआई|सफ्टवेयर|technology|tech|software|internet|ai)' THEN 'Technology'
                WHEN (title || ' ' || summary) ~* '(स्वास्थ्य|अस्पताल|चिकित्सा|रोग|औषधि|health|hospital|medical|disease)' THEN 'Health'
                WHEN (title || ' ' || summary) ~* '(मनोरञ्जन|चलचित्र|फिल्म|सिनेमा|कलाकार|संगीत|entertainment|movie|film|music)' THEN 'Entertainment'
                WHEN (title || ' ' || summary) ~* '(मौसम|वर्षा|बाढी|पहिरो|भूकम्प|आगलागी|weather|flood|landslide|earthquake|storm)' THEN 'Disaster & Weather'
                WHEN (title || ' ' || summary) ~* '(प्रहरी|अपराध|गिरफ्तार|दुर्घटना|सुरक्षा|police|crime|arrest|accident|security)' THEN 'Crime & Security'
                WHEN (title || ' ' || summary) ~* '(नेपाल|नेपाली|राष्ट्रिय|देशभर|काठमाडौं|nepal|national)' THEN 'National'
                ELSE 'Other'
            END,
            research_flags =
                (CASE WHEN COALESCE(summary,'')='' THEN jsonb_build_array('headline_only_no_article_summary') ELSE '[]'::jsonb END) ||
                (CASE WHEN published_at IS NULL THEN jsonb_build_array('publication_time_unknown') ELSE '[]'::jsonb END) ||
                (CASE WHEN published_at < NOW() - INTERVAL '48 hours' THEN jsonb_build_array('possibly_old_news') ELSE '[]'::jsonb END) ||
                (CASE WHEN source_count >= 2 THEN jsonb_build_array('similar_headline_seen_in_multiple_sources') ELSE '[]'::jsonb END) ||
                (CASE WHEN source_count >= 3 AND published_at >= NOW() - INTERVAL '6 hours' THEN jsonb_build_array('breaking_candidate_requires_editorial_verification') ELSE '[]'::jsonb END),
            evidence_status = CASE WHEN source_count >= 2 THEN 'multiple_source_headline_match_only'
                                   WHEN COALESCE(summary,'')='' THEN 'headline_only_single_source'
                                   ELSE 'single_source_with_summary' END,
            is_breaking_candidate = (source_count >= 3 AND published_at >= NOW() - INTERVAL '6 hours'),
            duplicate_group_key = md5(lower(title))
            WHERE category = 'Uncategorized' OR duplicate_group_key IS NULL
        """)

def add(title, summary, url, source, published_at=None):
    if not title or not url.startswith(("http://", "https://")):
        return "duplicate"
    category = _research_category(title, summary)
    with conn() as c:
        existing = c.execute(
            "SELECT id,sources,source_count,published_at,created FROM stories WHERE url=%s",
            (url,)
        ).fetchone()
        if existing:
            names = list(existing["sources"] or [])
            if source not in names:
                names.append(source)
                flags, evidence, breaking = _research_metadata(names, published_at or existing["published_at"], existing["created"], summary or existing.get("summary", ""))
                _record_story_source(c, existing["id"], source, title, summary, url, published_at)
                c.execute(
                    """UPDATE stories SET sources=%s,source_count=%s,
                       published_at=COALESCE(published_at,%s),research_flags=%s,
                       evidence_status=%s,is_breaking_candidate=%s,updated_at=NOW()
                       WHERE id=%s""",
                    (Jsonb(names), len(names), published_at, Jsonb(flags), evidence, breaking, existing["id"])
                )
                return "matched"
            _record_story_source(c, existing["id"], source, title, summary, url, published_at)
            return "duplicate"

        rows = c.execute(
            """SELECT id,title,summary,sources,source_count,category,published_at,created
               FROM stories WHERE status <> 'published'
               ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        match = None
        for row in rows:
            score = _title_similarity(title, row["title"])
            same_category = row["category"] == category or row["category"] in ("Other", "Uncategorized") or category == "Other"
            if score >= 0.84 and same_category:
                match = row
                break

        if match:
            names = list(match["sources"] or [])
            if source not in names:
                names.append(source)
            flags, evidence, breaking = _research_metadata(names, match["published_at"] or published_at, match["created"], match["summary"] or summary)
            _record_story_source(c, match["id"], source, title, summary, url, published_at)
            c.execute(
                """UPDATE stories SET sources=%s,source_count=%s,
                   summary=CASE WHEN summary='' AND %s<>'' THEN %s ELSE summary END,
                   published_at=COALESCE(published_at,%s),research_flags=%s,
                   evidence_status=%s,is_breaking_candidate=%s,updated_at=NOW()
                   WHERE id=%s""",
                (Jsonb(names), len(names), (summary or "")[:4000], (summary or "")[:4000],
                 published_at, Jsonb(flags), evidence, breaking, match["id"])
            )
            return "matched"

        names = [source]
        flags, evidence, breaking = _research_metadata(names, published_at, summary=summary)
        group_key = hashlib.sha256(_normalized_title(title).encode("utf-8")).hexdigest()[:20]
        row = c.execute(
            """INSERT INTO stories(
                title,summary,url,source_name,sources,source_count,category,draft,status,
                published_at,research_flags,evidence_status,is_breaking_candidate,duplicate_group_key
            ) VALUES(%s,%s,%s,%s,%s,1,%s,'','draft',%s,%s,%s,%s,%s)
            RETURNING id""",
            (title[:400], (summary or "")[:4000], url, source, Jsonb(names), category,
             published_at, Jsonb(flags), evidence, breaking, group_key)
        ).fetchone()
        sid = row["id"]
        _record_story_source(c, sid, source, title, summary, url, published_at)
        c.execute(
            "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
            ("story_collected", "A story was collected and classified for editorial research.", Jsonb({
                "story_id": sid, "source": source, "category": category, "evidence_status": evidence
            }))
        )
    return "new"


def _collect_one(feed):
    result = {
        "source_id": feed["id"], "source": feed["name"],
        "status": "ok", "items_seen": 0, "new": 0,
        "matched": 0, "duplicates": 0, "error": None
    }
    try:
        with conn() as c:
            c.execute("UPDATE sources SET last_checked=NOW() WHERE id=%s", (feed["id"],))
        logger.info("Checking news source: %s", feed["name"])
        parsed = _fetch_feed(feed["url"])
        entries = parsed.entries[:50]
        result["items_seen"] = len(entries)
        for entry in entries:
            title = _plain_text(entry.get("title", "") if isinstance(entry, dict) else getattr(entry, "title", ""))
            link = str(entry.get("link", "") if isinstance(entry, dict) else (getattr(entry, "link", "") or "")).strip()
            summary = _plain_text(entry.get("summary", "") if isinstance(entry, dict) else (getattr(entry, "summary", "") or getattr(entry, "description", "")))
            published_at = _published_datetime(entry) if isinstance(entry, dict) else None
            if not title or not link.startswith(("https://", "http://")):
                result["duplicates"] += 1
                continue
            outcome = add(title, summary, link, feed["name"], published_at)
            result["duplicates" if outcome == "duplicate" else outcome] += 1
        with conn() as c:
            c.execute("""
                UPDATE sources
                SET last_checked=NOW(), last_success=NOW(), last_error=NULL,
                    last_item_count=%s, consecutive_failures=0
                WHERE id=%s
            """, (len(entries), feed["id"]))
        logger.info("News source checked: %s (%s entries)", feed["name"], len(entries))
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:300]
        with conn() as c:
            c.execute("""
                UPDATE sources
                SET last_checked=NOW(), last_error=%s, consecutive_failures=consecutive_failures+1
                WHERE id=%s
            """, (result["error"], feed["id"]))
        logger.warning("News source failed: %s: %s", feed["name"], result["error"])
    return result


def collect():
    with conn() as c:
        feeds = c.execute(
            "SELECT id,name,url FROM sources WHERE enabled=TRUE ORDER BY name"
        ).fetchall()

    # Fetch publishers concurrently so slow or blocked websites do not
    # prevent the remaining sources from being checked in the same cycle.
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="nd-source") as pool:
        results = list(pool.map(_collect_one, feeds))

    totals = {
        "checked": len(results),
        "new": sum(x["new"] for x in results),
        "matched": sum(x["matched"] for x in results),
        "duplicates": sum(x["duplicates"] for x in results),
        "failed": sum(1 for x in results if x["status"] == "error"),
        "sources": results
    }
    with conn() as c:
        c.execute(
            "INSERT INTO activity_logs(event_type,message,details) VALUES(%s,%s,%s)",
            ("collection_finished", "News source collection run finished.", Jsonb({
                key: value for key, value in totals.items() if key != "sources"
            }))
        )
    return totals


def publish(sid, manual=False):
    # Facebook publishing is intentionally locked until Phase 9.
    return False, "Facebook publishing is disabled until Phase 9."


def cycle():
    """Collect feeds automatically during the requested Nepal-time monitoring window."""
    now = datetime.now().astimezone()
    local = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kathmandu"))
    if local.hour < 5 or (local.hour > 22 or (local.hour == 22 and local.minute > 55)):
        return
    logger.info("Automatic collection cycle started (Nepal time %s).", local.strftime("%H:%M"))
    try:
        result = collect()
        logger.info(
            "Automatic collection finished: %s sources, %s new stories, %s failures.",
            result["checked"], result["new"], result["failed"]
        )
    except Exception:
        logger.exception("Scheduled news collection failed.")


# Initialize the schema only when a DATABASE_URL is configured. A connection
# problem is reported by /ready rather than crashing the web process.
if DATABASE_URL:
    try:
        init()
        seed_default_sources()
        _backfill_research_fields()
    except Exception:
        logger.exception("PostgreSQL schema initialization or default source setup failed.")


scheduler = BackgroundScheduler(timezone="Asia/Kathmandu")
scheduler.add_job(
    cycle, "interval", minutes=5, id="automatic-news-collection",
    replace_existing=True, max_instances=1, coalesce=True,
    next_run_time=datetime.now(timezone.utc)
)
if DATABASE_URL:
    try:
        scheduler.start()
        logger.info("Automatic Nepali news collection scheduler started.")
    except Exception:
        logger.exception("Automatic news collection scheduler could not start.")


LOGIN = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Admin login</title><style>body{background:#0b1220;color:white;font:16px system-ui;display:grid;place-items:center;min-height:90vh}.box{background:#152238;padding:28px;border-radius:16px}input,button{padding:12px;margin:6px;border-radius:8px}</style><div class=box><h2>NayaDrishti Admin</h2><p>{{error}}</p><form method=post><input name=password type=password placeholder='Admin password' required><button>Sign in</button></form></div>"""
PANEL = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>NayaDrishti Newsroom</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#0b1220;color:#eef4ff;font:14px system-ui;margin:0;padding:22px;max-width:1180px;margin:auto}h1{margin:8px 0}h2{margin:0 0 12px}.muted{color:#9aabc2}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.card{background:#152238;border:1px solid #30425c;border-radius:14px;padding:16px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.stat{background:#0e192a;border:1px solid #30425c;padding:12px;border-radius:10px}.stat strong{font-size:23px;display:block}.stat span{color:#9aabc2;font-size:12px}input,button{padding:10px;border-radius:8px;margin:4px;border:1px solid #40536e}input{background:#0b1423;color:white;max-width:100%}button{background:#75e0c0;color:#071521;border:0;font-weight:700;cursor:pointer}button.secondary{background:#263a55;color:#eef4ff;border:1px solid #40536e}button.danger{background:#572e3b;color:#ffe7ed;border:1px solid #87475c}button:disabled{opacity:.5;cursor:wait}.feed{border-top:1px solid #30425c;padding:12px 0;display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.feed small{display:block;color:#9aabc2;overflow-wrap:anywhere}.feed-actions{display:flex;gap:4px;flex-wrap:wrap}.pill{font-size:11px;padding:3px 8px;border-radius:20px;background:#263a55}.ok{color:#75e0c0}.bad{color:#ff9eae}.warn{color:#ffd58a}.story{border-top:1px solid #30425c;padding:12px 0}.story h3{margin:0 0 5px;font-size:15px}.story a{color:#8bc4ff}@media(max-width:700px){body{padding:12px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.feed{align-items:flex-start}}
</style>
<div class=top><div><h1>NayaDrishti AI Newsroom</h1><p class=muted>Automatic Nepali news collection · refreshed every 5 minutes</p></div><a href=/admin/logout style=color:#8bc4ff>Sign out</a></div>
<div class=grid><div class=stat><strong id=total>—</strong><span>Total sources</span></div><div class=stat><strong id=enabled>—</strong><span>Enabled sources</span></div><div class=stat><strong id=healthy>—</strong><span>Healthy sources</span></div><div class=stat><strong id=storiesCount>—</strong><span>Collected stories</span></div></div>
<div class=card><h2>Automatic source setup</h2><p class=muted>NayaDrishti preloads available public Nepali news RSS feeds. You do not need to enter feed links. You can still add or manage sources below if needed.</p><form id=addForm><input id=sourceName placeholder='Source name' required maxlength=100><input id=sourceUrl placeholder='https://example.com/feed' required style='width:min(560px,95%)'><button id=addBtn>Add source</button></form><p id=message class=muted aria-live=polite></p></div>
<div class=card><div class=top><div><h2>News sources</h2><p class=muted>Enable, edit, check health or remove a source.</p></div><button id=collectBtn>Collect news now</button></div><div id=feeds>Loading sources…</div></div>
<div class=card><h2>Latest collected stories</h2><p class=muted>Original article links are kept for editorial verification. Stories are not published to Facebook.</p><div id=stories>Loading…</div></div>
<script>
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path,method='GET',body){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
async function load(){try{const d=await api('/api/admin/status');$('total').textContent=d.summary.total_sources;$('enabled').textContent=d.summary.enabled_sources;$('healthy').textContent=d.summary.healthy_sources;$('storiesCount').textContent=d.summary.stories;
$('feeds').innerHTML=d.sources.map(s=>'<div class=feed><div><strong>'+esc(s.name)+'</strong> '+(s.enabled?'<span class="pill ok">Enabled</span>':'<span class=pill>Disabled</span>')+' '+(s.last_error?'<span class="pill bad">Error</span>':s.last_success&&s.last_item_count>0?'<span class="pill ok">Healthy</span>':s.last_success&&s.last_item_count===0?'<span class="pill warn">Connected · no items</span>':s.last_checked?'<span class="pill warn">Checked · no success</span>':'<span class="pill warn">Not checked</span>')+'<small>'+esc(s.url)+'</small><small>Last checked: '+esc(s.last_checked||'Never')+' · Items: '+s.last_item_count+' · Failed runs: '+s.consecutive_failures+'</small>'+(s.last_error?'<small class=bad>'+esc(s.last_error)+'</small>':'')+'</div><div class=feed-actions><button class=secondary data-action=toggle data-id='+s.id+' data-enabled='+(s.enabled?'false':'true')+'>'+(s.enabled?'Disable':'Enable')+'</button><button class=secondary data-action=edit data-id='+s.id+' data-name="'+esc(s.name)+'" data-url="'+esc(s.url)+'">Edit</button><button class=danger data-action=delete data-id='+s.id+'>Remove</button></div></div>').join('')||'<p class=muted>No sources yet. Add your first RSS feed above.</p>';
$('stories').innerHTML=d.stories.map(s=>'<div class=story><h3>'+esc(s.title)+'</h3><p class=muted>'+esc(s.category||'Other')+' · '+esc(s.source_name)+' · '+s.source_count+' source match(es) · '+esc(s.status)+'</p><p>'+esc(s.summary||'No summary provided by feed.')+'</p><p class=muted>'+esc((s.research_flags||[]).join(' · '))+' · Evidence: '+esc(s.evidence_status||'single_source')+(s.is_breaking_candidate?' · BREAKING CANDIDATE — verify before use':'')+'</p><a href="'+esc(s.url)+'" target=_blank rel=noopener>Open original article</a></div>').join('')||'<p class=muted>No stories collected yet.</p>';
}catch(e){$('message').textContent=e.message}}
$('addForm').addEventListener('submit',async e=>{e.preventDefault();$('addBtn').disabled=true;try{await api('/api/admin/sources','POST',{name:$('sourceName').value,url:$('sourceUrl').value});$('message').textContent='Source added.';$('sourceName').value='';$('sourceUrl').value='';await load()}catch(err){$('message').textContent=err.message}finally{$('addBtn').disabled=false}});
$('feeds').addEventListener('click',async e=>{const b=e.target.closest('button[data-action]');if(!b)return;const id=b.dataset.id;try{if(b.dataset.action==='toggle'){await api('/api/admin/sources/'+id,'PATCH',{enabled:b.dataset.enabled==='true'})}else if(b.dataset.action==='edit'){const name=prompt('Source name:',b.dataset.name);if(name===null)return;const url=prompt('RSS / Atom feed URL:',b.dataset.url);if(url===null)return;await api('/api/admin/sources/'+id,'PATCH',{name,url})}else if(b.dataset.action==='delete'){if(!confirm('Remove this source? Previously collected stories will remain.'))return;await api('/api/admin/sources/'+id,'DELETE')}await load()}catch(err){alert(err.message)}});
$('collectBtn').addEventListener('click',async()=>{const b=$('collectBtn');b.disabled=true;b.textContent='Collecting…';$('message').textContent='Checking enabled RSS feeds…';try{const d=await api('/api/admin/collect','POST',{});$('message').textContent='Checked '+d.checked+' source(s): '+d.new+' new stories, '+d.matched+' similar-story matches, '+d.duplicates+' duplicates, '+d.failed+' failures.';await load();if(d.failed)alert('Some sources failed. Their error details are shown in Source Health.')}catch(e){$('message').textContent=e.message}finally{b.disabled=false;b.textContent='Collect news now'}});
load();
setInterval(load, 60000);
</script>"""


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
            """SELECT id,title,summary,url,source_name,source_count,draft,status,post_id,
                      category,published_at,research_flags,evidence_status,is_breaking_candidate
               FROM stories ORDER BY id DESC LIMIT 100"""
        ).fetchall()
        summary = c.execute("""
            SELECT
              COUNT(*)::int AS total_sources,
              COUNT(*) FILTER (WHERE enabled)::int AS enabled_sources,
              COUNT(*) FILTER (WHERE enabled AND last_success IS NOT NULL AND last_error IS NULL AND last_item_count > 0)::int AS healthy_sources,
              COUNT(*) FILTER (WHERE enabled AND last_error IS NOT NULL)::int AS error_sources,
              COUNT(*) FILTER (WHERE enabled AND last_checked IS NULL)::int AS unchecked_sources,
              COUNT(*) FILTER (WHERE enabled AND last_success IS NOT NULL AND last_error IS NULL AND last_item_count=0)::int AS connected_empty_sources,
              COUNT(*) FILTER (WHERE enabled AND last_checked IS NOT NULL AND last_success IS NULL AND last_error IS NULL)::int AS checked_without_success_sources
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
