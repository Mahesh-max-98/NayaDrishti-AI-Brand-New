import json
import os
import urllib.error
import urllib.request

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

HOME_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101827">
<title>NayaDrishti AI | Clear news. Clear perspective.</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--line:#24334a;--muted:#9aabc2;--white:#f5f8ff;--blue:#66a8ff;--mint:#75e0c0}
*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:Inter,system-ui,sans-serif;color:var(--white);background:radial-gradient(ellipse at 85% 0%,#183456 0,transparent 38%),radial-gradient(ellipse at 0% 65%,#123b3c 0,transparent 32%),var(--bg)}
.wrap{width:min(1120px,calc(100% - 40px));margin:auto}header{height:76px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #9aabc226}
.brand{display:flex;align-items:center;gap:12px;font-weight:750}.mark{width:40px;height:40px;display:grid;place-items:center;border-radius:13px;color:#071521;font-size:20px;font-weight:900;background:linear-gradient(135deg,var(--mint),var(--blue))}.brand small{display:block;color:var(--muted);font-size:11px;font-weight:500;letter-spacing:1.5px;margin-top:2px}
.status{color:var(--mint);border:1px solid #75e0c044;background:#75e0c010;padding:8px 12px;border-radius:999px;font-size:12px}main{padding:76px 0 56px}.hero{max-width:790px;margin:0 auto;text-align:center}
.eyebrow{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);background:#ffffff08;color:#b8c9df;border-radius:999px;padding:8px 13px;font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--mint)}
h1{margin:24px 0 18px;font-size:clamp(42px,7vw,76px);line-height:1.04;letter-spacing:-3.5px}h1 span{background:linear-gradient(100deg,#fff 15%,#8bc4ff 55%,#75e0c0);color:transparent;background-clip:text}
.intro{max-width:630px;margin:auto;color:var(--muted);font-size:17px;line-height:1.8}.actions{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin:30px 0 58px}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:13px 19px;border-radius:12px;font-weight:700;font-size:14px;border:1px solid var(--line);background:#ffffff08;color:inherit;text-decoration:none}.primary{color:#071521;border:0;background:linear-gradient(110deg,var(--mint),#83bdff)}
.section-label{text-align:center;color:#b8c9df;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:17px}.features{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.feature{min-height:155px;padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#ffffff0b,#ffffff04);color:inherit;text-decoration:none;display:block;transition:transform .2s,border-color .2s}.feature:hover{transform:translateY(-3px);border-color:#66a8ff99}
.ico{width:38px;height:38px;display:grid;place-items:center;border-radius:12px;background:#75e0c018;color:var(--mint);font-size:18px;margin-bottom:15px}.feature h2{font-size:16px;margin:0 0 8px}.feature p{color:var(--muted);font-size:13px;line-height:1.65;margin:0}
.note{text-align:center;color:#8294ad;font-size:12px;margin:25px auto 0}footer{border-top:1px solid #9aabc226;padding:22px 0;color:#8294ad;font-size:12px}footer .wrap{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:700px){main{padding-top:54px}.features{grid-template-columns:1fr}h1{letter-spacing:-2px}.intro{font-size:15px}header{height:68px}}
</style></head><body><div class="wrap">
<header><a class="brand" href="/" style="color:inherit;text-decoration:none"><span class="mark">N</span><span>NayaDrishti AI<small>NEWS • INSIGHT • PERSPECTIVE</small></span></a><span class="status">● Foundation online</span></header>
<main><section class="hero"><div class="eyebrow"><span class="dot"></span> A fresh perspective on Nepali news</div>
<h1>Clear news.<br><span>Clear perspective.</span></h1>
<p class="intro">A smarter space to collect, understand and review news from Nepal. Built to make useful information easier to follow — with clarity, context and responsibility.</p>
<div class="actions"><a class="btn primary" href="#features">Explore the platform →</a><a class="btn" href="/health">System status</a></div></section>
<section id="features"><div class="section-label">The platform we're building</div><div class="features">
<a class="feature" href="/assistant"><div class="ico">◈</div><h2>News discovery</h2><p>Open the AI assistant to explore topics and understand news in Nepali.</p></a>
<a class="feature" href="/assistant"><div class="ico">✧</div><h2>AI assistance</h2><p>Ask questions and get helpful explanations in Nepali.</p></a>
<div class="feature"><div class="ico">✓</div><h2>Editorial review</h2><p>Editorial review tools are planned for a later stage.</p></div>
</div><p class="note">Stage 2 introduces the AI assistant. News feeds and editorial tools will follow in later stages.</p></section></main>
<footer><div class="wrap"><span>© 2026 NayaDrishti AI</span><span>Built for clarity. Designed for Nepal.</span></div></footer>
</div></body></html>"""

ASSISTANT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0b1220"><title>AI Assistant | NayaDrishti AI</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#111c2e;--line:#283a54;--muted:#9aabc2;--white:#f5f8ff;--mint:#75e0c0;--blue:#83bdff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 80% 0%,#183456 0,transparent 38%),var(--bg);color:var(--white);font-family:Inter,system-ui,sans-serif;min-height:100vh}
.top{height:70px;border-bottom:1px solid #ffffff20;display:flex;align-items:center;justify-content:space-between;padding:0 max(20px,calc((100% - 900px)/2))}
a{color:var(--blue);text-decoration:none}.brand{font-weight:750;color:var(--white)}.back{font-size:14px}
main{width:min(900px,calc(100% - 28px));margin:32px auto}.heading{text-align:center;margin:28px 0}.heading h1{font-size:clamp(27px,5vw,40px);margin:0 0 10px}.heading p{color:var(--muted);margin:0;line-height:1.6}
.chat{border:1px solid var(--line);border-radius:20px;background:#111c2edb;overflow:hidden;box-shadow:0 20px 70px #0003}
.chat-head{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}.online{font-size:12px;color:var(--mint)}
.messages{height:min(52vh,520px);min-height:300px;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:14px}
.msg{max-width:85%;padding:13px 15px;border-radius:15px;line-height:1.7;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}.bot{align-self:flex-start;background:#1b2b42;border:1px solid #ffffff12}.user{align-self:flex-end;background:#24516a}.hint{font-size:12px;color:var(--muted);padding:0 20px 12px}
form{display:flex;gap:10px;padding:15px;border-top:1px solid var(--line)}textarea{flex:1;resize:vertical;min-height:48px;max-height:130px;border:1px solid var(--line);border-radius:12px;padding:13px;background:#0b1423;color:var(--white);font:inherit;outline:none}textarea:focus{border-color:var(--blue)}button{border:0;border-radius:12px;padding:0 20px;font-weight:750;background:linear-gradient(110deg,var(--mint),var(--blue));color:#071521;cursor:pointer}button:disabled{opacity:.55;cursor:wait}
.disclaimer{text-align:center;color:#8294ad;font-size:11px;line-height:1.6;margin:15px auto;max-width:700px}
@media(max-width:540px){.messages{height:55vh;padding:14px}.msg{max-width:94%}form{padding:10px}button{padding:0 14px}.top{height:62px}}
</style></head><body>
<header class="top"><a class="brand" href="/">NayaDrishti AI</a><a class="back" href="/">← Back to homepage</a></header>
<main><section class="heading"><h1>AI News Assistant</h1><p>Ask your question in English or Nepali. News explanations and answers are generated in Nepali.</p></section>
<section class="chat"><div class="chat-head"><strong>नेपाली समाचार सहायक</strong><span class="online">● AI assistant</span></div>
<div class="messages" id="messages" aria-live="polite"><div class="msg bot">नमस्कार! म NayaDrishti AI समाचार सहायक हुँ। तपाईं नेपाली समाचार, कुनै विषयको पृष्ठभूमि वा सामान्य जानकारीबारे प्रश्न सोध्न सक्नुहुन्छ। म उपलब्ध जानकारीका आधारमा नेपालीमा जवाफ दिनेछु।</div></div>
<div class="hint">कृपया संवेदनशील व्यक्तिगत जानकारी नलेख्नुहोस्।</div>
<form id="chatForm"><textarea id="prompt" maxlength="2000" placeholder="आफ्नो प्रश्न यहाँ लेख्नुहोस्..." required></textarea><button id="send" type="submit">Send</button></form></section>
<p class="disclaimer">AI ले कहिलेकाहीँ गलत वा अपूर्ण जानकारी दिन सक्छ। ताजा समाचार र महत्वपूर्ण तथ्यहरू विश्वसनीय स्रोतबाट पुष्टि गर्नुहोस्। यो सहायक आफैँ समाचार प्रकाशित गर्दैन।</p></main>
<script>
const form=document.getElementById('chatForm'),input=document.getElementById('prompt'),send=document.getElementById('send'),messages=document.getElementById('messages');
const history=[];
function addMessage(text,kind){const node=document.createElement('div');node.className='msg '+kind;node.textContent=text;messages.appendChild(node);messages.scrollTop=messages.scrollHeight;return node;}
form.addEventListener('submit',async(e)=>{e.preventDefault();const text=input.value.trim();if(!text)return;addMessage(text,'user');history.push({role:'user',content:text});input.value='';send.disabled=true;send.textContent='...';const waiting=addMessage('जवाफ तयार हुँदैछ…','bot');
try{const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:history.slice(-12)})});const data=await response.json();waiting.textContent=data.reply||data.error||'माफ गर्नुहोस्, अहिले जवाफ उपलब्ध भएन।';if(data.reply)history.push({role:'assistant',content:data.reply});}
catch(err){waiting.textContent='सर्भरसँग सम्पर्क हुन सकेन। कृपया केही समयपछि फेरि प्रयास गर्नुहोस्।';}
finally{send.disabled=false;send.textContent='Send';input.focus();messages.scrollTop=messages.scrollHeight;}
});
input.addEventListener('keydown',(e)=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
</script></body></html>"""

@app.get("/")
def home():
    return render_template_string(HOME_PAGE)

@app.get("/assistant")
def assistant():
    return render_template_string(ASSISTANT_PAGE)

@app.get("/health")
def health():
    return jsonify({"service": "NayaDrishti AI", "status": "ok", "stage": 2})

@app.post("/api/chat")
def chat():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({
            "error": "AI service is not configured yet. The administrator must add GEMINI_API_KEY in the Render environment settings."
        }), 503

    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list) or not messages or len(messages) > 12:
        return jsonify({"error": "Please send a valid conversation with up to 12 messages."}), 400

    contents = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("content")
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        text = text.strip()[:2000]
        if text:
            contents.append({
                "role": "user" if role == "user" else "model",
                "parts": [{"text": text}]
            })

    if not contents or contents[-1]["role"] != "user":
        return jsonify({"error": "Please enter a question first."}), 400

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "systemInstruction": {
            "parts": [{
                "text": (
                    "You are NayaDrishti AI, a careful Nepali news and information assistant. "
                    "Reply in clear, natural Nepali (Devanagari script) by default, even when the "
                    "question is written in English. The user may use English for admin and development "
                    "conversation, but public news explanations must be in Nepali. Never invent current "
                    "news, dates, quotes, sources, or statistics. If you cannot verify a current claim, "
                    "say so clearly and ask the user to check trusted news sources. Separate confirmed "
                    "facts from uncertainty. Do not claim that you have browsed the live web."
                )
            }]
        },
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 900}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
        candidates = result.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        answer = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not answer:
            return jsonify({"error": "The AI returned an empty response. Please try again."}), 502
        return jsonify({"reply": answer})
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            message = "AI usage limit reached. Please try again later or check the API quota."
            status = 429
        elif exc.code in (400, 401, 403, 404):
            message = "AI configuration error. The administrator should check the Gemini API key and model in Render."
            status = 502
        else:
            message = "The AI provider is temporarily unavailable. Please try again."
            status = 502
        return jsonify({"error": message}), status
    except (urllib.error.URLError, TimeoutError):
        return jsonify({"error": "The AI provider could not be reached. Please try again later."}), 502
    except (ValueError, KeyError, IndexError, TypeError):
        return jsonify({"error": "The AI response could not be processed. Please try again."}), 502

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
