import os,json,sqlite3,secrets,urllib.parse,urllib.request,urllib.error,re
from datetime import datetime,timezone
from difflib import SequenceMatcher
from functools import wraps
import feedparser
from flask import Blueprint,request,session,redirect,render_template_string,jsonify
from apscheduler.schedulers.background import BackgroundScheduler

bp=Blueprint("automation",__name__)
DB=os.environ.get("DATABASE_PATH","/tmp/nayadrishti.db")
def conn():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;return c
def init():
 with conn() as c:
  c.execute("CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,name TEXT,url TEXT UNIQUE,enabled INTEGER DEFAULT 1)")
  c.execute("CREATE TABLE IF NOT EXISTS stories(id INTEGER PRIMARY KEY,title TEXT,summary TEXT,url TEXT UNIQUE,source_name TEXT,sources TEXT,source_count INTEGER,draft TEXT,status TEXT,post_id TEXT,created TEXT,published TEXT)")
  c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)")
  c.execute("INSERT OR IGNORE INTO settings VALUES('auto','0')")
def getset(k,d="0"):
 with conn() as c:r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()
 return r["value"] if r else d
def setset(k,v):
 with conn() as c:c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v)))
def auth(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get("nd_admin"):
   return (jsonify({"error":"Sign in first."}),401) if request.path.startswith("/api/") else redirect("/admin/login")
  return f(*a,**kw)
 return w
def draft(title,summary,url):
 key=os.getenv("GEMINI_API_KEY")
 if not key:return ""
 model=os.getenv("GEMINI_MODEL","gemini-2.5-flash")
 prompt=("नेपाली भाषामा तथ्यमा आधारित छोटो फेसबुक समाचार पोस्ट लेख। स्रोतमा नभएको तथ्य नथप। "
 "शीर्षक र ३-५ वाक्य लेख। अन्त्यमा स्रोत URL राख।\nशीर्षक: "+title+
 "\nविवरण: "+(summary or "")[:4000]+"\nस्रोत: "+url)
 body={"contents":[{"role":"user","parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":450}}
 req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=30) as r:x=json.loads(r.read().decode())
  return "\n".join(p.get("text","") for p in x.get("candidates",[{}])[0].get("content",{}).get("parts",[])).strip()
 except Exception:return ""
def add(title,summary,url,source):
 if not title or not url.startswith(("http://","https://")):return False
 with conn() as c:
  if c.execute("SELECT id FROM stories WHERE url=?",(url,)).fetchone():return False
  rows=c.execute("SELECT id,title,sources,source_count FROM stories WHERE status!='published' ORDER BY id DESC LIMIT 120").fetchall()
  match=None
  norm=lambda s:re.sub(r"\W+"," ",s.lower()).strip()
  for row in rows:
   if SequenceMatcher(None,norm(title),norm(row["title"])).ratio()>=.86:match=row;break
  if match:
   names=json.loads(match["sources"] or "[]")
   if source not in names:names.append(source)
   c.execute("UPDATE stories SET sources=?,source_count=? WHERE id=?",(json.dumps(names,ensure_ascii=False),len(names),match["id"]))
   return True
  now=datetime.now(timezone.utc).isoformat()
  c.execute("INSERT INTO stories(title,summary,url,source_name,sources,source_count,draft,status,created) VALUES(?,?,?,?,?,1,'','draft',?)",(title[:400],(summary or "")[:4000],url,source,json.dumps([source],ensure_ascii=False),now))
  sid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
 text=draft(title,summary,url)
 with conn() as c:c.execute("UPDATE stories SET draft=? WHERE id=?",(text,sid))
 return True
def collect():
 init();added=0
 with conn() as c:feeds=c.execute("SELECT name,url FROM sources WHERE enabled=1").fetchall()
 for f in feeds:
  try:
   parsed=feedparser.parse(f["url"])
   for e in parsed.entries[:20]:
    if add(getattr(e,"title","").strip(),getattr(e,"summary",""),getattr(e,"link","").strip(),f["name"]):added+=1
  except Exception:pass
 return added
def publish(sid,manual=False):
 token=os.getenv("FB_PAGE_ACCESS_TOKEN");page=os.getenv("FB_PAGE_ID")
 if not token or not page:return False,"Facebook Page credentials are not configured."
 with conn() as c:s=c.execute("SELECT * FROM stories WHERE id=?",(sid,)).fetchone()
 if not s:return False,"Story not found."
 if s["status"]=="published":return False,"Already published."
 if not s["draft"]:return False,"AI draft missing. Check GEMINI_API_KEY and collect again."
 if not manual and s["source_count"]<2:return False,"Automatic publishing needs confirmation from at least two different feeds."
 ver=os.getenv("FB_GRAPH_VERSION","v27.0")
 endpoint=f"https://graph.facebook.com/{ver}/{urllib.parse.quote(page,safe='')}/feed"
 data=urllib.parse.urlencode({"message":s["draft"],"access_token":token}).encode()
 req=urllib.request.Request(endpoint,data=data,headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=30) as r:out=json.loads(r.read().decode())
  pid=out.get("id")
  if not pid:return False,"Facebook did not return a post ID."
  with conn() as c:c.execute("UPDATE stories SET status='published',post_id=?,published=? WHERE id=?",(pid,datetime.now(timezone.utc).isoformat(),sid))
  return True,pid
 except urllib.error.HTTPError as e:
  try:msg=json.loads(e.read().decode()).get("error",{}).get("message","Facebook API error")
  except Exception:msg="Facebook API error"
  return False,msg[:250]
 except Exception:return False,"Facebook connection failed."
def cycle():
 try:
  if getset("auto")!="1":return
  collect()
  with conn() as c:rows=c.execute("SELECT id FROM stories WHERE status='draft' AND draft!='' AND source_count>=2 ORDER BY id LIMIT 2").fetchall()
  for r in rows:publish(r["id"])
 except Exception:pass
init()
scheduler=BackgroundScheduler(timezone="Asia/Kathmandu")
scheduler.add_job(cycle,"interval",minutes=15,id="auto-publish",replace_existing=True,max_instances=1,coalesce=True)
if os.getenv("ADMIN_PASSWORD"):scheduler.start()

LOGIN="""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Admin login</title><style>body{background:#0b1220;color:white;font:16px system-ui;display:grid;place-items:center;min-height:90vh}.box{background:#152238;padding:28px;border-radius:16px}input,button{padding:12px;margin:6px;border-radius:8px}</style><div class=box><h2>NayaDrishti Admin</h2><p>{{error}}</p><form method=post><input name=password type=password placeholder='Admin password' required><button>Sign in</button></form></div>"""
PANEL="""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>NayaDrishti Admin</title><style>body{background:#0b1220;color:#eef;font:14px system-ui;margin:0;padding:20px;max-width:1000px;margin:auto}.card{background:#152238;border:1px solid #30425c;border-radius:14px;padding:16px;margin:12px 0}input,button{padding:10px;border-radius:8px;margin:4px}button{background:#75e0c0;border:0;font-weight:bold}a{color:#8bc4ff}.muted{color:#aab8cc}pre{white-space:pre-wrap}</style><h1>NayaDrishti AI Admin</h1><a href=/admin/logout>Sign out</a><div class=card><h3>Facebook</h3><p id=fb>Loading…</p><h3>Automatic publishing</h3><p id=auto></p><button onclick=toggle()>Toggle auto publishing</button></div><div class=card><h3>Add RSS feed</h3><input id=n placeholder='Source name'><input id=u placeholder='RSS feed URL' style='width:55%'><button onclick=add()>Add feed</button><p id=msg></p><div id=feeds></div></div><button onclick=collect()>Collect news now</button><h2>News drafts / published posts</h2><p class=muted>Auto mode publishes only stories matched across at least two configured feeds. Review manually before using auto mode.</p><div id=stories>Loading…</div><script>
async function api(p,b){let r=await fetch(p,{method:b?'POST':'GET',headers:b?{'Content-Type':'application/json'}:{},body:b?JSON.stringify(b):undefined}),d=await r.json();if(!r.ok)throw Error(d.error||'Failed');return d}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(){let d=await api('/api/admin/status');fb.textContent=d.facebook?'Connected credentials detected (hidden)':'Not connected — configure FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN in Render';auto.textContent=d.auto?'ON':'OFF';feeds.innerHTML=d.sources.map(s=>'<p>'+esc(s.name)+' · '+esc(s.url)+'</p>').join('')||'No RSS feeds added';stories.innerHTML=d.stories.map(s=>'<div class=card><h3>'+esc(s.title)+'</h3><p class=muted>'+esc(s.source_name)+' · '+s.source_count+' feed match(es) · '+esc(s.status)+'</p><pre>'+esc(s.draft||'AI draft not available. Check GEMINI_API_KEY.')+'</pre><a href="'+esc(s.url)+'" target=_blank rel=noopener>Original source</a><p>'+(s.status==='published'?'Published: '+esc(s.post_id):'<button onclick=pub('+s.id+')>Publish reviewed draft</button>')+'</p></div>').join('')||'No news yet.'}
async function add(){try{await api('/api/admin/sources',{name:n.value,url:u.value});msg.textContent='Feed added';n.value='';u.value='';load()}catch(e){msg.textContent=e.message}}
async function collect(){try{let d=await api('/api/admin/collect',{});alert('New or updated stories: '+d.added);load()}catch(e){alert(e.message)}}
async function toggle(){try{await api('/api/admin/auto',{});load()}catch(e){alert(e.message)}}
async function pub(id){if(!confirm('Publish this reviewed post to Facebook?'))return;try{await api('/api/admin/publish/'+id,{});alert('Published');load()}catch(e){alert(e.message)}}
load()</script>"""
@bp.get("/admin/login")
def login():return render_template_string(LOGIN,error="")
@bp.post("/admin/login")
def login_post():
 p=os.getenv("ADMIN_PASSWORD","")
 if p and secrets.compare_digest(request.form.get("password",""),p):session["nd_admin"]=True;return redirect("/admin")
 return render_template_string(LOGIN,error="Incorrect password or admin is not configured."),401
@bp.get("/admin/logout")
def logout():session.clear();return redirect("/admin/login")
@bp.get("/admin")
@auth
def panel():return render_template_string(PANEL)
@bp.get("/api/admin/status")
@auth
def status():
 with conn() as c:
  feeds=c.execute("SELECT name,url FROM sources ORDER BY name").fetchall()
  rows=c.execute("SELECT id,title,url,source_name,source_count,draft,status,post_id FROM stories ORDER BY id DESC LIMIT 50").fetchall()
 return jsonify({"facebook":bool(os.getenv("FB_PAGE_ID") and os.getenv("FB_PAGE_ACCESS_TOKEN")),"auto":getset("auto")=="1","sources":[dict(x) for x in feeds],"stories":[dict(x) for x in rows]})
@bp.post("/api/admin/sources")
@auth
def source_add():
 d=request.get_json(silent=True) or {};name=str(d.get("name","")).strip()[:100];url=str(d.get("url","")).strip()
 if not name or not url.startswith(("https://","http://")):return jsonify({"error":"Enter a source name and valid RSS URL."}),400
 try:
  with conn() as c:c.execute("INSERT INTO sources(name,url) VALUES(?,?)",(name,url))
 except sqlite3.IntegrityError:return jsonify({"error":"This feed is already added."}),409
 return jsonify({"ok":True})
@bp.post("/api/admin/collect")
@auth
def collect_now():return jsonify({"added":collect()})
@bp.post("/api/admin/auto")
@auth
def auto_toggle():
 new="0" if getset("auto")=="1" else "1"
 if new=="1" and not(os.getenv("FB_PAGE_ID") and os.getenv("FB_PAGE_ACCESS_TOKEN") and os.getenv("GEMINI_API_KEY")):return jsonify({"error":"Configure FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN and GEMINI_API_KEY in Render first."}),400
 setset("auto",new);return jsonify({"auto":new=="1"})
@bp.post("/api/admin/publish/<int:sid>")
@auth
def publish_now(sid):
 ok,result=publish(sid,True)
 return (jsonify({"ok":True,"post_id":result}) if ok else (jsonify({"error":result}),400))
