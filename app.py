import os
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101827">
  <meta name="description" content="NayaDrishti AI — a clearer perspective on Nepali news.">
  <title>NayaDrishti AI | Clear news. Clear perspective.</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1220; --panel:#111c2e; --line:#24334a; --muted:#9aabc2; --white:#f5f8ff; --blue:#66a8ff; --mint:#75e0c0; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--white); background:radial-gradient(ellipse at 85% 0%,#183456 0,transparent 38%),radial-gradient(ellipse at 0% 65%,#123b3c 0,transparent 32%),var(--bg); }
    a { color:inherit; text-decoration:none; }
    .wrap { width:min(1120px,calc(100% - 40px)); margin:auto; }
    header { height:76px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid rgba(154,171,194,.15); }
    .brand { display:flex; align-items:center; gap:12px; font-weight:750; letter-spacing:.2px; }
    .mark { width:40px; height:40px; display:grid; place-items:center; border-radius:13px; color:#071521; font-size:20px; font-weight:900; background:linear-gradient(135deg,var(--mint),var(--blue)); box-shadow:0 8px 28px #66a8ff30; }
    .brand small { display:block; color:var(--muted); font-size:11px; font-weight:500; letter-spacing:1.5px; margin-top:2px; }
    .status { color:var(--mint); border:1px solid #75e0c044; background:#75e0c010; padding:8px 12px; border-radius:999px; font-size:12px; }
    main { padding:76px 0 56px; }
    .hero { max-width:790px; margin:0 auto; text-align:center; }
    .eyebrow { display:inline-flex; gap:8px; align-items:center; border:1px solid var(--line); background:#ffffff08; color:#b8c9df; border-radius:999px; padding:8px 13px; font-size:12px; }
    .dot { width:7px; height:7px; border-radius:50%; background:var(--mint); box-shadow:0 0 12px var(--mint); }
    h1 { margin:24px 0 18px; font-size:clamp(42px,7vw,76px); line-height:1.04; letter-spacing:-3.5px; }
    h1 span { background:linear-gradient(100deg,#fff 15%,#8bc4ff 55%,#75e0c0); color:transparent; background-clip:text; -webkit-background-clip:text; }
    .intro { max-width:630px; margin:0 auto; color:var(--muted); font-size:17px; line-height:1.8; }
    .actions { display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin:30px 0 58px; }
    .btn { display:inline-flex; align-items:center; justify-content:center; padding:13px 19px; border-radius:12px; font-weight:700; font-size:14px; border:1px solid var(--line); background:#ffffff08; }
    .btn.primary { color:#071521; border:0; background:linear-gradient(110deg,var(--mint),#83bdff); }
    .section-label { text-align:center; color:#b8c9df; font-size:12px; letter-spacing:2px; text-transform:uppercase; margin-bottom:17px; }
    .features { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
    .feature { min-height:155px; padding:22px; border:1px solid var(--line); border-radius:18px; background:linear-gradient(145deg,#ffffff0b,#ffffff04); }
    .ico { width:38px; height:38px; display:grid; place-items:center; border-radius:12px; background:#75e0c018; color:var(--mint); font-size:18px; margin-bottom:15px; }
    .feature h2 { font-size:16px; margin:0 0 8px; }
    .feature p { color:var(--muted); font-size:13px; line-height:1.65; margin:0; }
    .note { text-align:center; color:#8294ad; font-size:12px; margin:25px auto 0; }
    footer { border-top:1px solid rgba(154,171,194,.15); padding:22px 0; color:#8294ad; font-size:12px; }
    footer .wrap { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }
    @media(max-width:700px) { main{padding-top:54px} .features{grid-template-columns:1fr} h1{letter-spacing:-2px} .intro{font-size:15px} header{height:68px} }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <a class="brand" href="/" aria-label="NayaDrishti AI home">
        <span class="mark">N</span>
        <span>NayaDrishti AI<small>NEWS • INSIGHT • PERSPECTIVE</small></span>
      </a>
      <span class="status"><span class="dot" style="display:inline-block;margin-right:7px"></span>Foundation online</span>
    </header>
    <main>
      <section class="hero">
        <div class="eyebrow"><span class="dot"></span> A fresh perspective on Nepali news</div>
        <h1>Clear news.<br><span>Clear perspective.</span></h1>
        <p class="intro">A smarter space to collect, understand and review news from Nepal. Built to make useful information easier to follow — with clarity, context and responsibility.</p>
        <div class="actions">
          <a class="btn primary" href="#features">Explore the platform&nbsp; →</a>
          <a class="btn" href="/health">System status</a>
        </div>
      </section>
      <section id="features">
        <div class="section-label">The platform we're building</div>
        <div class="features">
          <article class="feature"><div class="ico">◈</div><h2>News discovery</h2><p>Bring news from selected sources into one organised workspace.</p></article>
          <article class="feature"><div class="ico">✧</div><h2>AI assistance</h2><p>Make complex stories easier to understand with helpful summaries and context.</p></article>
          <article class="feature"><div class="ico">✓</div><h2>Editorial review</h2><p>Review information carefully before anything is approved for publication.</p></article>
        </div>
        <p class="note">This is the first foundation release. News feeds, AI tools and the admin workspace will be added and tested in later stages.</p>
      </section>
    </main>
    <footer><div class="wrap"><span>© 2026 NayaDrishti AI</span><span>Built for clarity. Designed for Nepal.</span></div></footer>
  </div>
</body>
</html>"""

@app.get("/")
def home():
    return render_template_string(PAGE)

@app.get("/health")
def health():
    return jsonify({"service": "NayaDrishti AI", "status": "ok", "stage": 1})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
