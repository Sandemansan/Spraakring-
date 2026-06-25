#!/usr/bin/env python3
"""
SpraaKring - Communicatiehulp voor mensen die niet kunnen spreken
Gebruik : python spraakring.py
Vereisten: pip install flask anthropic
"""

import os
import json
import random
import webbrowser
import threading
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

# ──────────────────────────────────────────────
# API-sleutel automatisch laden
# ──────────────────────────────────────────────
def load_api_key():
    """Laad sleutel — zoekt op meerdere plekken zodat hij niet verdwijnt."""
    appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "SpraaKring")
    paths = [
        os.path.join(appdata, "api_key.txt"),                                      # permanent AppData
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt"),   # naast het script
    ]
    for p in paths:
        if os.path.exists(p):
            k = open(p).read().strip()
            if k:
                return k
    return (os.environ.get("GEMINI_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("API_KEY") or "")

def save_api_key(key):
    """Sla sleutel permanent op in AppData."""
    appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "SpraaKring")
    os.makedirs(appdata, exist_ok=True)
    with open(os.path.join(appdata, "api_key.txt"), "w") as f:
        f.write(key)

SERVER_API_KEY = load_api_key()
SERVER_EL_KEY  = os.environ.get("ELEVENLABS_API_KEY", "")

# ──────────────────────────────────────────────
# Fallback-opties (zonder API-sleutel)
# ──────────────────────────────────────────────
FALLBACK = [
    ["Ja, inderdaad", "Nee, niet echt", "Vertel meer", "Dat weet ik niet", "Goed idee", "Interessant!"],
    ["Helemaal mee eens", "Twijfelachtig", "Absoluut!", "Misschien wel", "Waarom dat?", "Dat begrijp ik"],
    ["Haha, ja!", "Dat is grappig", "Wat denk jij?", "Laten we zien", "Nee dankjewel", "Mooi zo!"],
]

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_TEMPLATE

@app.route("/api/savekey", methods=["POST"])
def api_savekey():
    key = (request.json or {}).get("key", "").strip()
    if key:
        save_api_key(key)
        global SERVER_API_KEY
        SERVER_API_KEY = key
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Lege sleutel"})

@app.route("/api/test")
def api_test():
    key = SERVER_API_KEY
    if not key:
        return jsonify({"ok": False, "error": "Geen sleutel"})
    try:
        raw = _call_gemini(key, "Zeg alleen: werkt")
        return jsonify({"ok": True, "response": raw})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/models")
def api_models():
    """Lijst beschikbare Gemini-modellen voor deze sleutel."""
    import urllib.request
    key = SERVER_API_KEY
    if not key:
        return jsonify({"error": "Geen sleutel"})
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=50"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        names = [m["name"] for m in data.get("models", [])]
        return jsonify({"models": names})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/tts", methods=["POST"])
def api_tts():
    """Roep ElevenLabs TTS aan en geef mp3 terug als base64."""
    import urllib.request, base64
    data    = request.json or {}
    text    = data.get("text", "").strip()
    voice_id= data.get("voice_id", "21m00Tcm4TlvDq8ikWAM")
    el_key  = data.get("el_key", "").strip() or SERVER_EL_KEY
    if not el_key or not text:
        return jsonify({"error": "geen sleutel of tekst"}), 400
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=payload, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("xi-api-key", el_key)
    req.add_header("Accept", "audio/mpeg")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            audio = r.read()
        return jsonify({"audio": base64.b64encode(audio).decode()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/status")
def api_status():
    return jsonify({"has_key": bool(SERVER_API_KEY), "has_el": bool(SERVER_EL_KEY)})

@app.route("/api/suggest", methods=["POST"])
def suggest():
    data = request.json or {}
    context     = data.get("context", "")
    parent_word = data.get("parent_word", "")
    api_key     = data.get("api_key", "").strip() or SERVER_API_KEY
    history     = data.get("history", [])
    language    = data.get("language", "nl-NL")
    count       = max(3, min(8, int(data.get("count", 6))))

    lang_name = {"nl-NL": "Nederlands", "en-US": "English",
                 "fr-FR": "Français",   "de-DE": "Deutsch"}.get(language, "Nederlands")

    if not api_key:
        return jsonify({"suggestions": random.choice(FALLBACK)[:count]})

    # Bouw prompt
    hist_lines = []
    for h in history[-6:]:
        who = "Ander" if h.get("speaker") == "other" else "Gebruiker"
        hist_lines.append(f"{who}: {h.get('text','')}")
    hist_text = "\n".join(hist_lines) or "(geen)"

    if parent_word:
        prompt = f"""Je helpt een persoon die niet kan praten om deel te nemen aan een gesprek.

Gespreksgeschiedenis:
{hist_text}

De gebruiker heeft net gezegd: "{parent_word}"
Dit was in reactie op: "{context}"

Genereer precies {count} VERVOLGOPTIES die dieper ingaan op "{parent_word}".
Regels:
- Maximaal 5 woorden per optie
- Gevarieerd: details, emoties, vragen, humor, meningen
- Logisch passend bij "{parent_word}" in deze context
- Volledig in {lang_name}

Geef ALLEEN een JSON-array terug, niets anders:
["optie 1", "optie 2", ...]"""
    else:
        prompt = f"""Je helpt een persoon die niet kan praten om deel te nemen aan een gesprek.

Gespreksgeschiedenis:
{hist_text}

Iemand heeft zojuist gezegd: "{context}"

Genereer precies {count} eerste ANTWOORDOPTIES die deze persoon zou kunnen zeggen.
Regels:
- Maximaal 5 woorden per optie
- Gevarieerd: minstens 1-2 negatieve/eerlijke reacties (zoals "Niet zo goed", "Ik voel me moe", "Dat vind ik minder"), én positieve, humoristische, vragend
- Passend bij de context
- Volledig in {lang_name}

Geef ALLEEN een JSON-array terug, niets anders:
["optie 1", "optie 2", ...]"""

    # Auto-detecteer API op basis van sleutelprefix
    # Gemini-sleutels beginnen met "AIza", Anthropic met "sk-ant-"
    try:
        if api_key.startswith("sk-ant-"):
            raw = _call_anthropic(api_key, prompt)
        else:
            # Gemini: AIza... of AQ... of andere Google-sleutels
            raw = _call_gemini(api_key, prompt)

        # Gemini verpakt JSON soms in ```json ... ``` — dat strippen we weg
        import re as _re
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1]
        if clean.rstrip().endswith("```"):
            clean = clean.rstrip().rsplit("\n", 1)[0]
        clean = clean.strip()

        suggestions = None

        # Poging 1: volledige JSON-array
        s, e = clean.find("["), clean.rfind("]") + 1
        if s >= 0 and e > s:
            try:
                suggestions = json.loads(clean[s:e])
            except Exception:
                pass

        # Poging 2: regex — werkt ook bij afgebroken array (geen sluit-])
        if not suggestions:
            start = clean.find("[")
            fragment = clean[start:] if start >= 0 else clean
            found = _re.findall(r'"((?:[^"\\]|\\.)*)"', fragment)
            if found:
                suggestions = found

        if not suggestions:
            print(f"[SpraaKring] Kon geen opties extraheren uit: {clean[:300]}")
            suggestions = random.choice(FALLBACK)

        return jsonify({"suggestions": suggestions[:count]})

    except Exception as ex:
        print(f"[SpraaKring] API fout: {ex}")
        return jsonify({"suggestions": random.choice(FALLBACK)[:count], "error": str(ex)})


def _call_gemini(api_key, prompt):
    """Roep Gemini Flash aan — probeert meerdere modelnamen."""
    import urllib.request, urllib.error
    models = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-flash-latest",
    ]
    last_err = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.9}
        }).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} op {model}: {e.read().decode()[:200]}"
            continue
        except Exception as e:
            last_err = str(e)
            break
    raise Exception(f"Alle modellen gefaald. Laatste fout: {last_err}")


def _call_anthropic(api_key, prompt):
    """Roep Claude Haiku aan (Anthropic)."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ──────────────────────────────────────────────
# HTML / CSS / JS  (alles in één template)
# ──────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>SpraaKring</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}

body{
  background:#0d0d1a;color:#fff;
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  height:100vh;overflow:hidden;user-select:none;
  -webkit-tap-highlight-color:transparent;
}

/* ── Layout ── */
#app{display:flex;height:100vh}

/* ── Sidebar ── */
#sidebar{
  width:240px;min-width:240px;
  background:#12122a;
  border-right:1px solid rgba(255,255,255,.07);
  display:flex;flex-direction:column;
  padding:14px;gap:10px;
}
#sidebar h2{
  font-size:11px;text-transform:uppercase;letter-spacing:2px;
  color:rgba(255,255,255,.3);padding-bottom:8px;
  border-bottom:1px solid rgba(255,255,255,.06);
}
#transcript{
  flex:1;overflow-y:auto;
  display:flex;flex-direction:column;gap:7px;
  padding-right:2px;
}
.t-entry{
  padding:8px 11px;border-radius:12px;
  font-size:13px;line-height:1.45;
  animation:slideIn .3s ease;
}
.t-entry.other{
  background:rgba(255,255,255,.07);
  border-bottom-left-radius:3px;
}
.t-entry.user{
  background:linear-gradient(135deg,#4a2c8a,#2d1b69);
  align-self:flex-end;border-bottom-right-radius:3px;
  text-align:right;
}
.t-label{font-size:10px;color:rgba(255,255,255,.38);margin-bottom:2px}

#clear-btn{
  padding:8px;background:rgba(255,255,255,.05);
  border:none;border-radius:8px;
  color:rgba(255,255,255,.35);cursor:pointer;
  font-size:12px;transition:background .2s;
}
#clear-btn:hover{background:rgba(255,255,255,.1)}

/* ── Main ── */
#main{flex:1;display:flex;flex-direction:column;min-width:0}

/* ── Toolbar ── */
#toolbar{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;
  background:rgba(0,0,0,.25);
  border-bottom:1px solid rgba(255,255,255,.05);
  flex-shrink:0;
}
#mic-btn{
  display:flex;align-items:center;gap:8px;
  padding:9px 18px;border:none;border-radius:24px;
  background:linear-gradient(135deg,#1a3a5c,#2a5080);
  color:#fff;font-size:14px;font-weight:600;
  cursor:pointer;transition:all .25s;flex-shrink:0;
}
#mic-btn.active{
  background:linear-gradient(135deg,#b02020,#d93030);
  animation:pulseMic 1.6s infinite;
}
#status-text{
  flex:1;font-size:13px;color:rgba(255,255,255,.45);
  text-align:center;min-width:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
#speech-btn{
  background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.18);color:#fff;
  width:34px;height:34px;border-radius:50%;
  cursor:pointer;font-size:16px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .2s;
}
#speech-btn.muted{
  background:rgba(180,40,40,.25);
  border-color:rgba(200,60,60,.5);
}
#settings-btn{
  background:transparent;
  border:1px solid rgba(255,255,255,.18);color:#fff;
  width:34px;height:34px;border-radius:50%;
  cursor:pointer;font-size:15px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;
}

/* ── Ring area ── */
#ring-area{
  flex:1;position:relative;
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;
}
#ring-canvas{position:absolute;inset:0;pointer-events:none}
#ring-container{position:absolute;inset:0}

/* ── Heard strip ── */
#heard-strip{
  position:absolute;bottom:14px;
  left:50%;transform:translateX(-50%);
  display:flex;flex-direction:column;align-items:center;gap:3px;
  pointer-events:none;
}
#heard-label{
  font-size:10px;color:rgba(255,255,255,.22);
  text-transform:uppercase;letter-spacing:1.5px;
}
#heard-text{
  font-size:13px;color:rgba(255,255,255,.45);
  background:rgba(0,0,0,.35);
  padding:5px 14px;border-radius:16px;
  max-width:50vw;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}

/* ── Breadcrumb ── */
#breadcrumb{
  position:absolute;top:10px;
  left:50%;transform:translateX(-50%);
  display:flex;align-items:center;gap:5px;
  pointer-events:none;
}
.bc-item{
  font-size:11px;color:rgba(255,255,255,.3);
  background:rgba(255,255,255,.05);
  padding:3px 9px;border-radius:10px;
}
.bc-sep{color:rgba(255,255,255,.2);font-size:12px}

/* ── Bubbles ── */
.bubble{
  position:absolute;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  text-align:center;padding:10px;
  word-break:break-word;line-height:1.25;
  cursor:pointer;
  transition:box-shadow .2s,filter .2s;
}
.bubble:hover{
  filter:brightness(1.25);
  box-shadow:0 0 28px rgba(120,200,255,.35);
  z-index:10;
}
.bubble:active{filter:brightness(.9)}

.bubble.center{
  background:linear-gradient(135deg,#4a2c8a,#2d1b69);
  box-shadow:0 0 40px rgba(74,44,138,.5);
  cursor:default;z-index:5;
}
.bubble.center:hover{filter:none}

.bubble.option{
  background:linear-gradient(145deg,#1a3a5c,#2a5080);
  box-shadow:0 4px 18px rgba(0,0,0,.45);
  animation:popIn .4s cubic-bezier(.34,1.56,.64,1) both;
}
.bubble.speaking{
  background:linear-gradient(135deg,#0a5a5a,#009999) !important;
  box-shadow:0 0 30px rgba(0,200,200,.65) !important;
  animation:speakPulse .7s ease-in-out infinite !important;
}
.bubble.loading{
  background:rgba(255,255,255,.04);
  border:2px dashed rgba(255,255,255,.15);
  cursor:default;animation:none !important;
}
.bubble.loading:hover{filter:none;box-shadow:none}

.dots{display:flex;gap:4px}
.dots span{
  width:6px;height:6px;background:rgba(255,255,255,.35);
  border-radius:50%;animation:dotBounce .9s infinite;
}
.dots span:nth-child(2){animation-delay:.15s}
.dots span:nth-child(3){animation-delay:.3s}

/* ── Mic waves ── */
.mic-waves{display:flex;align-items:center;gap:2px;height:18px}
.mic-wave{
  width:3px;background:#fff;border-radius:2px;
  animation:waveAnim .7s infinite ease-in-out;
}
.mic-wave:nth-child(1){height:30%;animation-delay:0s}
.mic-wave:nth-child(2){height:70%;animation-delay:.1s}
.mic-wave:nth-child(3){height:100%;animation-delay:.2s}
.mic-wave:nth-child(4){height:70%;animation-delay:.1s}
.mic-wave:nth-child(5){height:30%;animation-delay:0s}

/* ── Settings modal ── */
#settings-modal{
  position:fixed;inset:0;background:rgba(0,0,0,.72);
  z-index:200;display:none;
  align-items:center;justify-content:center;
}
#settings-modal.open{display:flex}
.settings-panel{
  background:#14142e;
  border:1px solid rgba(255,255,255,.1);
  border-radius:18px;padding:30px;
  width:440px;max-width:92vw;
}
.settings-panel h2{font-size:18px;margin-bottom:22px}
.settings-panel label{
  display:block;font-size:11px;
  color:rgba(255,255,255,.42);
  text-transform:uppercase;letter-spacing:1px;
  margin-bottom:5px;
}
.settings-panel input,.settings-panel select{
  width:100%;padding:11px 14px;
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.13);
  border-radius:9px;color:#fff;font-size:14px;
  margin-bottom:14px;
}
.settings-panel select{appearance:none;cursor:pointer}
.settings-note{
  font-size:12px;color:rgba(255,255,255,.28);
  line-height:1.5;margin-bottom:18px;
}
.btn-row{display:flex;gap:10px;justify-content:flex-end}
.btn{
  padding:9px 22px;border-radius:9px;
  border:none;cursor:pointer;font-size:14px;font-weight:600;
}
.btn-p{background:linear-gradient(135deg,#4a2c8a,#6a3ca8);color:#fff}
.btn-s{background:rgba(255,255,255,.1);color:#fff}

/* ── Animations ── */
@keyframes popIn{
  0%{transform:translate(-50%,-50%) scale(0);opacity:0}
  100%{transform:translate(-50%,-50%) scale(1);opacity:1}
}
@keyframes pulseMic{
  0%,100%{box-shadow:0 0 0 0 rgba(200,40,40,.4)}
  50%{box-shadow:0 0 0 14px rgba(200,40,40,0)}
}
@keyframes speakPulse{
  0%,100%{box-shadow:0 0 18px rgba(0,200,200,.4)}
  50%{box-shadow:0 0 38px rgba(0,200,200,.85)}
}
@keyframes dotBounce{
  0%,80%,100%{transform:scale(.7);opacity:.45}
  40%{transform:scale(1.2);opacity:1}
}
@keyframes waveAnim{
  0%,100%{transform:scaleY(.5)}
  50%{transform:scaleY(1)}
}
@keyframes slideIn{
  from{opacity:0;transform:translateY(6px)}
  to{opacity:1;transform:translateY(0)}
}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:3px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:2px}

/* ── Grid mode ── */
#grid-section{display:none;flex:1;flex-direction:column;overflow-y:auto;padding:12px 14px;gap:10px}
#grid-center-label{text-align:center;font-size:13px;color:rgba(255,255,255,.42);padding:8px 12px;background:rgba(255,255,255,.05);border-radius:10px;line-height:1.4}
#options-grid{display:flex;flex-wrap:wrap;gap:10px}
.grid-option{flex:1 1 calc(50% - 10px);min-height:68px;background:linear-gradient(145deg,#1a3a5c,#2a5080);border-radius:16px;display:flex;align-items:center;justify-content:center;text-align:center;cursor:pointer;font-size:14px;font-weight:600;padding:12px 10px;color:#fff;line-height:1.3;word-break:break-word;box-shadow:0 4px 14px rgba(0,0,0,.4);transition:filter .2s,box-shadow .2s;animation:gridPop .35s cubic-bezier(.34,1.56,.64,1) both}
.grid-option:hover{filter:brightness(1.2);box-shadow:0 0 22px rgba(120,200,255,.3)}
.grid-option:active{filter:brightness(.85)}
.grid-option.speaking{background:linear-gradient(135deg,#0a5a5a,#009999)!important;box-shadow:0 0 24px rgba(0,200,200,.65)!important}
.grid-option.loading-cell{background:rgba(255,255,255,.04);border:2px dashed rgba(255,255,255,.12);pointer-events:none;animation:none}
@keyframes gridPop{0%{transform:scale(0);opacity:0}100%{transform:scale(1);opacity:1}}
.tb-icon-btn{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);color:#fff;width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:15px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .2s;padding:0}
.tb-icon-btn:hover{background:rgba(255,255,255,.17)}
.tb-icon-btn.active-mode{background:rgba(74,44,138,.55);border-color:rgba(120,80,200,.7)}
#sidebar.sb-hidden{display:none!important}
@media(max-width:640px){#sidebar{display:none}#status-text{font-size:11px}#mic-btn{padding:8px 12px;font-size:13px}#mic-label{display:none}#heard-strip{bottom:8px}}
</style>
</head>
<body>
<div id="app">

  <!-- ── Sidebar ── -->
  <div id="sidebar">
    <h2>Gesprek</h2>
    <div id="transcript">
      <div id="transcript-empty" style="color:rgba(255,255,255,.2);font-size:13px;text-align:center;margin-top:36px;line-height:1.6">
        Start een gesprek door op de microfoon te drukken
      </div>
    </div>
    <button id="clear-btn" onclick="clearAll()">🗑️ Gesprek wissen</button>
  </div>

  <!-- ── Main ── -->
  <div id="main">

    <!-- Toolbar -->
    <div id="toolbar">
      <button id="mic-btn" onclick="toggleMic()">
        <span id="mic-icon">🎙️</span>
        <span id="mic-label">Luisteren</span>
      </button>
      <button id="speech-btn" onclick="toggleSpeech()" title="Spraak aan/uit">🔊</button>
      <div id="status-text">Druk op Luisteren of spatiebalk</div>
      <button class="tb-icon-btn" id="chat-btn" onclick="toggleSidebar()" title="Gesprek tonen/verbergen">💬</button>
      <button class="tb-icon-btn" id="layout-btn" onclick="toggleLayout()" title="Weergave wisselen">⊞</button>
      <button class="tb-icon-btn" id="fs-btn" onclick="toggleFullscreen()" title="Volledig scherm">⛶</button>
      <button id="settings-btn" onclick="toggleSettings()" title="Instellingen">⚙️</button>
    </div>

    <!-- Ring -->
    <div id="ring-area">
      <canvas id="ring-canvas"></canvas>
      <div id="ring-container"></div>

      <div id="breadcrumb"></div>

      <div id="heard-strip">
        <div id="heard-label">Gehoord</div>
        <div id="heard-text">—</div>
      </div>
    </div>

    <!-- Grid (mobiel / optioneel) -->
    <div id="grid-section">
      <div id="grid-center-label">—</div>
      <div id="options-grid"></div>
    </div>

  </div>
</div>

<!-- Settings modal -->
<div id="settings-modal">
  <div class="settings-panel">
    <h2>⚙️ Instellingen</h2>

    <label>API-sleutel (Gemini of Anthropic)</label>
    <input type="password" id="api-key-input" placeholder="AIza... of sk-ant-..." />

    <label>Taal</label>
    <select id="lang-select">
      <option value="nl-NL">Nederlands</option>
      <option value="en-US">English</option>
      <option value="fr-FR">Français</option>
      <option value="de-DE">Deutsch</option>
    </select>

    <label>Aantal opties</label>
    <select id="count-select">
      <option value="4">4 opties</option>
      <option value="6" selected>6 opties (aanbevolen)</option>
      <option value="8">8 opties</option>
    </select>

    <label>Stem</label>
    <select id="voice-select">
      <option value="vrouw-normaal">♀ Vrouw — normaal</option>
      <option value="vrouw-langzaam">♀ Vrouw — langzaam</option>
      <option value="vrouw-snel">♀ Vrouw — snel</option>
      <option value="man-normaal">♂ Man — normaal</option>
      <option value="man-langzaam">♂ Man — langzaam</option>
      <option value="man-snel">♂ Man — snel</option>
      <option value="tiener">🧑 Tiener / jonger</option>
      <option value="kind">🧒 Kind</option>
    </select>

    <label>ElevenLabs stem-sleutel <span style="font-weight:400;opacity:.6">(optioneel — voor echte stemmen)</span></label>
    <input type="password" id="el-key-input" placeholder="sk_..." />
    <p class="settings-note" style="margin-top:4px">
      Gratis account via <strong>elevenlabs.io</strong> (10.000 tekens/maand).<br>
      Zonder deze sleutel gebruikt de app de browser-stem.
    </p>

    <div class="btn-row">
      <button class="btn btn-s" onclick="toggleSettings()">Annuleren</button>
      <button class="btn btn-p" onclick="saveSettings()">Opslaan</button>
    </div>
  </div>
</div>

<script>
// ════════════════════════════════════════════════
// State
// ════════════════════════════════════════════════
let apiKey       = localStorage.getItem("sk_key")    || "";
let language     = localStorage.getItem("sk_lang")   || "nl-NL";
let optCount     = Math.max(6, parseInt(localStorage.getItem("sk_count") || "6"));
let voicePreset  = localStorage.getItem("sk_voice") || "vrouw-normaal";
let speechOn     = localStorage.getItem("sk_speech") !== "off";
let conversation = [];           // [{speaker,text}]
let recognition  = null;
let isListening  = false;
let isSpeaking   = false;
let currentCtx   = "";           // last heard sentence
let breadcrumb   = [];           // selected words trail
let lastOptions  = [];           // for resize re-render
let layoutMode   = window.innerWidth < 640 ? "grid" : "ring";
let sidebarHidden= window.innerWidth < 640;
let silenceTimer = null;
let accTranscript= "";
let _sf          = "";   // finals van huidige herkenningssessie
let serverHasKey = false;
let serverElKey  = false;
let elKey        = localStorage.getItem("sk_el_key") || "";

// ════════════════════════════════════════════════
// Helpers
// ════════════════════════════════════════════════
const $  = id => document.getElementById(id);
const RC = $("ring-container");
const CV = $("ring-canvas");
const ctx2d = CV.getContext("2d");

function setStatus(t){ $("status-text").textContent = t }

function ringArea(){ return $("ring-area").getBoundingClientRect() }

function getCenter(){
  const r = ringArea();
  return { x: r.width/2, y: r.height/2 };
}

function getRadius(){
  const r = ringArea();
  return Math.min(r.width, r.height) * 0.32;
}

function getBubbleSz(isCenter){
  const r = ringArea();
  const b = Math.min(r.width, r.height);
  return isCenter ? b*0.19 : b*0.165;
}

function fitCanvas(){
  const r = ringArea();
  CV.width  = r.width;
  CV.height = r.height;
}

function drawLines(cx, cy, pts){
  fitCanvas();
  ctx2d.clearRect(0,0,CV.width,CV.height);
  ctx2d.strokeStyle = "rgba(255,255,255,.13)";
  ctx2d.lineWidth   = 1;
  pts.forEach(([bx,by])=>{
    ctx2d.beginPath();
    ctx2d.moveTo(cx, cy);
    ctx2d.lineTo(bx, by);
    ctx2d.stroke();
  });
}

// ════════════════════════════════════════════════
// Speech recognition
// ════════════════════════════════════════════════
function initRecognition(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    setStatus("⚠️ Spraakherkenning niet beschikbaar – gebruik Chrome");
    return false;
  }
  recognition = new SR();
  recognition.lang = language;
  // continuous=true altijd: voorkomt start/stop-bliepjes bij elke zin
  // Mobiel: accTranscript NIET gebruiken (anders sessie-overlap → herhaling)
  const _isMobile = window.innerWidth < 640 || /Android|iPhone|iPad/i.test(navigator.userAgent);
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onstart  = ()=>{ isListening=true; updateMicUI(); setStatus("🎙️ Aan het luisteren…"); };
  recognition.onerror  = e=>{ if(e.error!=="no-speech") console.warn("SR error:",e.error); };


  recognition.onend = ()=>{
    if(isListening){
      clearTimeout(silenceTimer);
      const final = _sf.trim();
      _sf = "";
      if(_isMobile){
        // Mobiel: verwerk alleen als niet in cooldown
        if(final) handleHeard(final);
      } else {
        if(final) accTranscript += final + " ";
      }
      try{ recognition.start(); }catch(_){}
    }
  };


  recognition.onresult = evt =>{
    _sf = "";
    let interim = "";
    for(let i=0; i<evt.results.length; i++){
      if(evt.results[i].isFinal) _sf += evt.results[i][0].transcript+" ";
      else interim += evt.results[i][0].transcript;
    }
    const display = (_isMobile ? (_sf + interim) : (accTranscript + _sf + interim)).trim();
    if(display) $("heard-text").textContent = display;

    if(!_isMobile){
      clearTimeout(silenceTimer);
      silenceTimer = setTimeout(()=>{
        const t = (accTranscript + _sf + interim).trim();
        if(t){ accTranscript=""; _sf=""; $("heard-text").textContent=t; handleHeard(t); }
      }, 950);
    } else {
      clearTimeout(silenceTimer);
      silenceTimer = setTimeout(()=>{
        const t = (_sf + interim).trim();
        if(t){ _sf=""; $("heard-text").textContent=t; handleHeard(t); }
      }, 1800);
    }
  };
  return true;
}

function toggleMic(){
  if(!recognition && !initRecognition()) return;
  if(isListening){
    isListening = false;
    recognition.stop();
    clearTimeout(silenceTimer);
    accTranscript = "";
    updateMicUI();
    setStatus("Luisteren gestopt");
  } else {
    isListening = true;
    try{ recognition.start(); }catch(_){
      recognition=null; initRecognition();
      try{ recognition.start(); }catch(e2){}
    }
  }
}

function updateMicUI(){
  const btn   = $("mic-btn");
  const icon  = $("mic-icon");
  const label = $("mic-label");
  // Stille feedback: trilling in plaats van bliep
  if(navigator.vibrate) navigator.vibrate(isListening ? [30] : [15, 30, 15]);
  if(isListening){
    btn.classList.add("active");
    label.textContent = "Stop";
    icon.innerHTML = `<div class="mic-waves">
      <div class="mic-wave"></div><div class="mic-wave"></div>
      <div class="mic-wave"></div><div class="mic-wave"></div>
      <div class="mic-wave"></div>
    </div>`;
  } else {
    btn.classList.remove("active");
    label.textContent = "Luisteren";
    icon.innerHTML = "🎙️";
  }
}

// ════════════════════════════════════════════════
// Conversation logic
// ════════════════════════════════════════════════
function handleHeard(text){
  clearTimeout(silenceTimer);
  _sf = "";
  if(navigator.vibrate) navigator.vibrate(40);
  currentCtx = text;
  breadcrumb = [];
  addToTranscript("other", text);
  generateOptions(text, null);
}

function addToTranscript(speaker, text){
  const t = $("transcript");
  $("transcript-empty") && $("transcript-empty").remove();
  conversation.push({speaker, text, ts: Date.now()});
  const el = document.createElement("div");
  el.className = `t-entry ${speaker}`;
  el.innerHTML = `<div class="t-label">${speaker==="other"?"👤 Ander":"💬 Jij"}</div><div>${text}</div>`;
  t.appendChild(el);
  t.scrollTop = t.scrollHeight;
}

function clearAll(){
  conversation=[];currentCtx="";breadcrumb=[];lastOptions=[];
  accTranscript="";clearTimeout(silenceTimer);
  if(layoutMode==="grid"){$("options-grid").innerHTML="";$("grid-center-label").textContent="\u2014";}
  $("transcript").innerHTML = `<div id="transcript-empty" style="color:rgba(255,255,255,.2);font-size:13px;text-align:center;margin-top:36px;line-height:1.6">Start een gesprek door op de microfoon te drukken</div>`;
  $("heard-text").textContent = "—";
  $("breadcrumb").innerHTML = "";
  renderInit();
}

// ════════════════════════════════════════════════
// AI suggestions
// ════════════════════════════════════════════════
async function generateOptions(context, parentWord){
  setStatus("Suggesties ophalen…");
  renderLoading();

  try{
    const res = await fetch("/api/suggest",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        context, parent_word: parentWord,
        api_key: apiKey, history: conversation.slice(-6),
        language, count: optCount
      })
    });
    const data = await res.json();
    const opts = data.suggestions || getFallback();
    lastOptions = opts;
    renderOptions(context, opts, parentWord);
    setStatus((apiKey||serverHasKey) ? "Tik om te zeggen · tik nogmaals voor meer opties" : "ℹ️ Geen API-sleutel — standaard-opties actief");
  } catch(e){
    const opts = getFallback();
    lastOptions = opts;
    renderOptions(context, opts, parentWord);
    setStatus("⚠️ Offline – standaard opties");
  }
}

function getFallback(){
  const pools = [
    ["Ja, inderdaad","Nee, niet echt","Vertel meer","Dat weet ik niet","Goed idee","Interessant!"],
    ["Helemaal mee eens","Twijfelachtig","Absoluut!","Misschien wel","Waarom dat?","Dat begrijp ik"],
    ["Haha, ja!","Dat is grappig","Wat denk jij?","Laten we zien","Nee dankjewel","Mooi zo!"],
  ];
  return pools[Math.floor(Math.random()*pools.length)].slice(0,optCount);
}

// ════════════════════════════════════════════════
// Rendering
// ════════════════════════════════════════════════
function clearRing(){
  RC.innerHTML = "";
  ctx2d.clearRect(0,0,CV.width,CV.height);
}

function makeBubble(text,sz,x,y,cls,delay=0){
  const el = document.createElement("div");
  el.className = `bubble ${cls}`;
  el.textContent = text;
  const fs = Math.max(10, sz * 0.115);
  el.style.cssText = `
    width:${sz}px;height:${sz}px;
    left:${x}px;top:${y}px;
    transform:translate(-50%,-50%) scale(${cls.includes("option")?0:1});
    font-size:${fs}px;
    animation-delay:${delay}s;
  `;
  return el;
}

function renderLoading(){
  if(layoutMode==="grid"){ renderLoadingGrid(); return; }
  clearRing();
  fitCanvas();
  const {x:cx,y:cy} = getCenter();
  const R   = getRadius();
  const sz  = getBubbleSz(false);
  const pts = [];

  for(let i=0;i<optCount;i++){
    const ang = (i*2*Math.PI/optCount) - Math.PI/2;
    const bx = cx + R*Math.cos(ang);
    const by = cy + R*Math.sin(ang);
    pts.push([bx,by]);
    const el = document.createElement("div");
    el.className = "bubble loading";
    el.style.cssText = `width:${sz}px;height:${sz}px;left:${bx}px;top:${by}px;transform:translate(-50%,-50%)`;
    el.innerHTML = `<div class="dots"><span></span><span></span><span></span></div>`;
    RC.appendChild(el);
  }
  drawLines(cx,cy,pts);
}

function renderOptions(context, options, parentWord){
  if(layoutMode==="grid"){ renderOptionsGrid(context, options, parentWord); return; }
  clearRing();
  const {x:cx,y:cy} = getCenter();
  const R      = getRadius();
  const csz    = getBubbleSz(true);
  const osz    = getBubbleSz(false);
  const pts    = [];

  // Center
  const cLabel = parentWord
    ? (parentWord.length>38 ? parentWord.slice(0,35)+"…" : parentWord)
    : (context.length>38    ? context.slice(0,35)+"…"   : context || "—");
  const cBub = makeBubble(cLabel, csz, cx, cy, "center");
  cBub.style.transform = "translate(-50%,-50%)";
  RC.appendChild(cBub);

  // Options
  options.forEach((txt,i)=>{
    const ang  = (i*2*Math.PI/options.length) - Math.PI/2;
    const bx   = cx + R*Math.cos(ang);
    const by   = cy + R*Math.sin(ang);
    pts.push([bx,by]);

    const el = makeBubble(txt, osz, bx, by, "option", i*0.055);
    el.addEventListener("click", ()=> selectOption(txt, el));
    el.addEventListener("touchend", e=>{ e.preventDefault(); selectOption(txt,el); });
    RC.appendChild(el);
  });

  drawLines(cx,cy,pts);
  updateBreadcrumb();
}

// ── Grid-modus ──
function renderLoadingGrid(){
  $("options-grid").innerHTML="";
  $("grid-center-label").textContent="Laden...";
  for(let i=0;i<optCount;i++){
    const el=document.createElement("div");
    el.className="grid-option loading-cell";
    el.innerHTML=`<div class="dots"><span></span><span></span><span></span></div>`;
    $("options-grid").appendChild(el);
  }
}
function renderOptionsGrid(context,options,parentWord){
  $("options-grid").innerHTML="";
  const label=parentWord||context||"\u2014";
  $("grid-center-label").textContent=label.length>60?label.slice(0,57)+"...":label;
  options.forEach((txt,i)=>{
    const el=document.createElement("div");
    el.className="grid-option";
    el.style.animationDelay=(i*0.06)+"s";
    el.textContent=txt;
    el.addEventListener("click",()=>selectOption(txt,el));
    el.addEventListener("touchend",e=>{e.preventDefault();selectOption(txt,el);});
    $("options-grid").appendChild(el);
  });
  updateBreadcrumb();
}
function applyLayoutMode(){
  const g=layoutMode==="grid";
  $("ring-area").style.display=g?"none":"";
  $("grid-section").style.display=g?"flex":"none";
  const lb=$("layout-btn");
  lb.textContent=g?"\u25cf":"\u229e";
  lb.title=g?"Ring-weergave":"Raster-weergave";
  g?lb.classList.add("active-mode"):lb.classList.remove("active-mode");
}
function toggleLayout(){
  layoutMode=layoutMode==="ring"?"grid":"ring";
  applyLayoutMode();
  if(lastOptions.length) renderOptions(currentCtx,lastOptions,breadcrumb[breadcrumb.length-1]||null);
}
function toggleSidebar(){
  sidebarHidden=!sidebarHidden;
  sidebarHidden?$("sidebar").classList.add("sb-hidden"):$("sidebar").classList.remove("sb-hidden");
  sidebarHidden?$("chat-btn").classList.remove("active-mode"):$("chat-btn").classList.add("active-mode");
}
function toggleFullscreen(){
  if(!document.fullscreenElement){
    document.documentElement.requestFullscreen().catch(()=>{});
    $("fs-btn").textContent="\u2715";
  } else {
    document.exitFullscreen();
    $("fs-btn").textContent="\u26f6";
  }
}
function renderInit(){
  // Show real options straight away — no mic needed to start
  currentCtx = "gesprek gestart";
  generateOptions("gesprek gestart", null);
}

function updateBreadcrumb(){
  const bc = $("breadcrumb");
  if(breadcrumb.length===0){ bc.innerHTML=""; return; }
  bc.innerHTML = breadcrumb.map((w,i)=>
    `<span class="bc-item">${w}</span>${i<breadcrumb.length-1?'<span class="bc-sep">›</span>':''}`
  ).join("");
}

// ════════════════════════════════════════════════
// Selection
// ════════════════════════════════════════════════
function selectOption(text, el){
  if(isSpeaking) return;
  el.classList.add("speaking");
  addToTranscript("user", text);
  setStatus(`Aan het zeggen: "${text}"`);

  speak(text, ()=>{
    el.classList.remove("speaking");
    breadcrumb.push(text);
    // Generate deeper options around chosen word
    generateOptions(currentCtx || text, text);
  });
}

// ════════════════════════════════════════════════
// Spraak aan/uit
// ════════════════════════════════════════════════
function toggleSpeech(){
  speechOn = !speechOn;
  localStorage.setItem("sk_speech", speechOn ? "on" : "off");
  updateSpeechBtn();
  setStatus(speechOn ? "🔊 Spraak aan" : "🔇 Spraak uit");
  if(!speechOn) window.speechSynthesis.cancel();
}

function updateSpeechBtn(){
  const btn = $("speech-btn");
  btn.textContent = speechOn ? "🔊" : "🔇";
  btn.classList.toggle("muted", !speechOn);
  btn.title = speechOn ? "Spraak uitzetten" : "Spraak aanzetten";
}

// ════════════════════════════════════════════════
// TTS
// ════════════════════════════════════════════════

const MALE_KW   = ["male","man","maarten","guy","david","mark","paul","thomas","koen","xander"];
const FEMALE_KW = ["female","woman","fenna","zira","eva","anna","lotte","claire","ellen","lisa","samantha"];
// ElevenLabs stem-IDs — eleven_multilingual_v2 model
const EL_VOICES = {
  "vrouw-normaal" : { id:"21m00Tcm4TlvDq8ikWAM", speed:1.0  },  // Rachel
  "vrouw-langzaam": { id:"EXAVITQu4vr4xnSDxMaL", speed:0.82 },  // Bella
  "vrouw-snel"    : { id:"AZnzlk1XvdvUeBnXmlld", speed:1.2  },  // Domi
  "man-normaal"   : { id:"pNInz6obpgDQGcFmaJgB", speed:1.0  },  // Adam
  "man-langzaam"  : { id:"VR6AewLTigWG4xSOukaG", speed:0.82 },  // Arnold
  "man-snel"      : { id:"TxGEqnHWrfWFTfGW9XjX", speed:1.2  },  // Josh
  "tiener"        : { id:"MF3mGyEYCl7XYWbV9V6O", speed:1.05 },  // Elli
  "kind"          : { id:"jBpfuIE2acCO8z3wKNLl", speed:1.08 },  // Gigi
};
const VOICE_PRESETS = {
  "vrouw-normaal" : { rate:0.88, pitch:1.02, gender:"female" },
  "vrouw-langzaam": { rate:0.70, pitch:1.00, gender:"female" },
  "vrouw-snel"    : { rate:1.15, pitch:1.02, gender:"female" },
  "man-normaal"   : { rate:0.85, pitch:0.92, gender:"male"   },
  "man-langzaam"  : { rate:0.68, pitch:0.90, gender:"male"   },
  "man-snel"      : { rate:1.10, pitch:0.93, gender:"male"   },
  "tiener"        : { rate:1.00, pitch:1.14, gender:"female" },
  "kind"          : { rate:1.05, pitch:1.26, gender:"female" },
};

// ── Browser TTS (fallback) ──
function speakBrowser(text, onEnd){
  if(!window.speechSynthesis || !speechOn){ onEnd&&onEnd(); return; }
  isSpeaking = true;
  window.speechSynthesis.cancel();

  const utt    = new SpeechSynthesisUtterance(text);
  const preset = VOICE_PRESETS[voicePreset] || VOICE_PRESETS["vrouw-normaal"];
  utt.rate = preset.rate;
  utt.lang = language;

  const voices = window.speechSynthesis.getVoices();
  const lang2  = language.split("-")[0];
  const pool   = voices.filter(v=> v.lang===language || v.lang.startsWith(lang2));
  const isNatural = v => /natural|neural|online/i.test(v.name);

  let chosen = null;
  if(preset.gender==="male"){
    chosen = pool.find(v=> MALE_KW.some(k=> v.name.toLowerCase().includes(k)));
  }
  if(!chosen){
    chosen = pool.find(v=> isNatural(v) && !MALE_KW.some(k=> v.name.toLowerCase().includes(k)));
    if(!chosen) chosen = pool.find(v=> FEMALE_KW.some(k=> v.name.toLowerCase().includes(k)));
    if(!chosen) chosen = pool[0]||null;
  }
  if(chosen) utt.voice = chosen;
  utt.pitch = (chosen && isNatural(chosen)) ? 1.0 : preset.pitch;

  utt.onend = utt.onerror = ()=>{ isSpeaking=false; onEnd&&onEnd(); };
  window.speechSynthesis.speak(utt);
}

// ── ElevenLabs TTS ──
async function speakEL(text, onEnd){
  if(!elKey && !serverElKey){ speakBrowser(text, onEnd); return; }
  isSpeaking = true;
  const key = elKey || "";
  const ev  = EL_VOICES[voicePreset] || EL_VOICES["vrouw-normaal"];

  const watchdog = setTimeout(()=>{ isSpeaking=false; onEnd&&onEnd(); }, 15000);
  const done = (callOnEnd=true)=>{ clearTimeout(watchdog); isSpeaking=false; if(callOnEnd) onEnd&&onEnd(); };

  try{
    const res = await fetch("/api/tts",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ text, voice_id: ev.id, el_key: key })
    });
    const d = await res.json();
    if(d.error || !d.audio) throw new Error(d.error||"geen audio");

    const bytes = atob(d.audio);
    const arr   = new Uint8Array(bytes.length);
    for(let i=0;i<bytes.length;i++) arr[i]=bytes.charCodeAt(i);
    const blob  = new Blob([arr],{type:"audio/mpeg"});
    const url   = URL.createObjectURL(blob);
    const aud   = new Audio(url);
    aud.onended = ()=>{ URL.revokeObjectURL(url); done(); };
    aud.onerror = ()=>{ URL.revokeObjectURL(url); done(); };
    const p = aud.play();
    if(p && p.catch) p.catch(e=>{ console.warn("play() geweigerd:",e); done(); speakBrowser(text,null); });
  }catch(e){
    console.warn("EL TTS mislukt:",e);
    done(false);
    isSpeaking=false;
    speakBrowser(text,onEnd);
  }
}

// ── Dispatcher ──
function speak(text, onEnd){
  if((elKey||serverElKey) && speechOn) speakEL(text, onEnd);
  else speakBrowser(text, onEnd);
}

// ════════════════════════════════════════════════
// Settings
// ════════════════════════════════════════════════
function toggleSettings(){
  const m = $("settings-modal");
  if(m.classList.contains("open")){
    m.classList.remove("open");
  } else {
    $("api-key-input").value  = apiKey;
    $("lang-select").value    = language;
    $("count-select").value   = optCount;
    $("voice-select").value  = voicePreset;
    $("el-key-input").value   = elKey;
    m.classList.add("open");
  }
}

function saveSettings(){
  apiKey      = $("api-key-input").value.trim();
  language    = $("lang-select").value;
  optCount    = parseInt($("count-select").value);
  voicePreset = $("voice-select").value;
  elKey       = $("el-key-input").value.trim();
  localStorage.setItem("sk_el_key", elKey);
  localStorage.setItem("sk_key",    apiKey);
  localStorage.setItem("sk_lang",   language);
  localStorage.setItem("sk_count",  optCount);
  localStorage.setItem("sk_voice", voicePreset);
  if(recognition) recognition.lang = language;
  toggleSettings();

  // Sla sleutel ook permanent op via server (zodat hij niet verdwijnt na herstart)
  if(apiKey){
    fetch("/api/savekey", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({key: apiKey})
    }).then(()=> setStatus("✓ Sleutel opgeslagen — blijft bewaard na herstart"))
      .catch(()=> setStatus("✓ Instellingen opgeslagen"));
  } else {
    setStatus("✓ Instellingen opgeslagen");
  }
}

$("settings-modal").addEventListener("click", e=>{
  if(e.target===$("settings-modal")) toggleSettings();
});

// ════════════════════════════════════════════════
// Keyboard
// ════════════════════════════════════════════════
document.addEventListener("keydown", e=>{
  if(e.code==="Space" && e.target===document.body){ e.preventDefault(); toggleMic(); }
  if(e.code==="Escape") $("settings-modal").classList.contains("open") && toggleSettings();
});

// ════════════════════════════════════════════════
// Resize
// ════════════════════════════════════════════════
let resizeT;
window.addEventListener("resize",()=>{
  clearTimeout(resizeT);
  resizeT=setTimeout(()=>{
    if(lastOptions.length){
      renderOptions(currentCtx, lastOptions, breadcrumb[breadcrumb.length-1]||null);
    } else {
      renderInit();
    }
  },180);
});

// ════════════════════════════════════════════════
// Init
// ════════════════════════════════════════════════
window.speechSynthesis.onvoiceschanged = ()=>{};
window.speechSynthesis.getVoices();
updateSpeechBtn();

// Check server key status, then render initial options
fetch('/api/status').then(r=>r.json()).then(d=>{
  serverHasKey = !!d.has_key;
  serverElKey  = !!d.has_el;
  if(!serverHasKey && !apiKey){
    setStatus("ℹ️ Voeg een API-sleutel toe via ⚙️ voor slimme AI-suggesties");
  }
}).catch(()=>{});

applyLayoutMode();
if(sidebarHidden)$("sidebar").classList.add("sb-hidden");
else $("chat-btn").classList.add("active-mode");
renderInit();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# Start
# ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    is_local = port == 5050

    if is_local:
        def open_browser():
            time.sleep(1.4)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=open_browser, daemon=True).start()
        print()
        print("  ╔═══════════════════════════════════╗")
        print("  ║   🎙️  SpraaKring gestart           ║")
        print(f"  ║   http://localhost:{port}            ║")
        print("  ║   Ctrl+C om te stoppen            ║")
        print("  ╚═══════════════════════════════════╝")
        print()

    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
