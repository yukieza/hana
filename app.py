import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

BASE = Path(__file__).parent
KEY_FILE = BASE / "key.txt"
LOG_DIR = BASE / "logs"
API_URL = "https://9router.leticia.my.id/v1/chat/completions"
MODELS = ["Free", "Main"]
TTS_SERVERS = [
    u.strip()
    for u in os.environ.get("TTS_SERVERS", "http://192.168.101.2:50021,http://192.168.101.3:50021").split(",")
    if u.strip()
]
VOICEVOX_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "8"))
STT_URL = os.environ.get("STT_URL", "http://192.168.101.2:9000")
_tts = {"u": None, "until": 0.0}


def tts_servers():
    now = time.time()
    if _tts["until"] > now and _tts["u"]:
        return [_tts["u"]] + [u for u in TTS_SERVERS if u != _tts["u"]]
    alive = []
    for u in TTS_SERVERS:
        try:
            if requests.get(f"{u}/version", timeout=2).ok:
                alive.append(u)
        except requests.RequestException:
            pass
    if alive:
        _tts.update(u=alive[0], until=now + 60)
    return alive

SYSTEM = """You are Hana, a friendly Japanese conversation partner for an Indonesian learner (around JLPT N4). The goal is kaiwa renshu.

Format every reply exactly like this:
1. Your Japanese reply: simple natural Japanese, 2-4 sentences, with follow-up questions to keep the conversation going.
2. A new line starting with "R:" containing the romaji of your whole Japanese reply.
3. If the user's Japanese had mistakes: a short "Koreksi:" section in Indonesian (salah -> benar + alasan singkat). Skip if there are no mistakes.

If the user writes in Indonesian or English, gently encourage them to answer in Japanese and show how to say it in Japanese.
Stay in character; be warm and encouraging."""


def get_key():
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError("API key belum ada. Buat file key.txt di folder kaiwa-renshu (isi API key router kamu)")


HISTORY = []
app = Flask(__name__)


def ask():
    last = None
    for model in MODELS:
        try:
            r = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {get_key()}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": SYSTEM}] + HISTORY,
                    "temperature": 0.8,
                },
                timeout=120,
            )
            r.raise_for_status()
            raw = r.content.decode("utf-8", errors="replace")
            data, _ = json.JSONDecoder().raw_decode(raw.strip())
            return data["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, IndexError) as e:
            last = e
    raise last


@app.post("/chat")
def chat():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify(error="kosong"), 400
    HISTORY.append({"role": "user", "content": text})
    try:
        reply = ask()
    except Exception as e:
        HISTORY.pop()
        return jsonify(error=str(e)), 502
    HISTORY.append({"role": "assistant", "content": reply})
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / f"{datetime.now():%Y-%m-%d}.md", "a", encoding="utf-8") as f:
        f.write(f"## Kamu\n\n{text}\n\n## Hana\n\n{reply}\n\n")
    return jsonify(reply=reply)


@app.post("/reset")
def reset():
    HISTORY.clear()
    return jsonify(ok=True)


@app.get("/tts")
def tts():
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify(error="kosong"), 400
    last = None
    for u in tts_servers():
        try:
            q = requests.post(
                f"{u}/audio_query",
                params={"text": text, "speaker": VOICEVOX_SPEAKER},
                timeout=15,
            )
            q.raise_for_status()
            w = requests.post(
                f"{u}/synthesis",
                params={"speaker": VOICEVOX_SPEAKER},
                json=q.json(),
                timeout=180,
            )
            w.raise_for_status()
            _tts.update(u=u, until=time.time() + 60)
            return Response(w.content, mimetype="audio/wav")
        except requests.RequestException as e:
            last = e
    return jsonify(error=str(last)), 502


@app.post("/stt")
def stt():
    f = request.files.get("audio")
    if not f:
        return jsonify(error="audio kosong"), 400
    try:
        r = requests.post(
            f"{STT_URL}/asr",
            params={"output": "json", "language": "ja"},
            files={"audio_file": (f.filename or "speech.webm", f.read())},
            timeout=180,
        )
        r.raise_for_status()
        return jsonify(text=(r.json().get("text") or "").strip())
    except Exception as e:
        return jsonify(error=str(e)), 502


PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kaiwa Renshu</title>
<style>
 body{font-family:sans-serif;background:#f5f2ea;margin:0 auto;max-width:720px}
 #chat{padding:12px;padding-bottom:90px}
 .msg{margin:10px 0;padding:10px 14px;border-radius:14px;white-space:pre-wrap;line-height:1.7}
 .you{background:#d9e8ff;margin-left:20%}
 .hana{background:#fff;margin-right:20%;box-shadow:0 1px 2px rgba(0,0,0,.08)}
 header{position:sticky;top:0;background:#f5f2ea;padding:10px 16px;display:flex;justify-content:space-between;align-items:center}
 button{border:0;border-radius:10px;padding:8px 14px;cursor:pointer;font-size:16px}
 #bar{position:fixed;bottom:0;left:0;right:0;display:flex;gap:8px;padding:10px;background:#f5f2ea;max-width:720px;margin:auto;box-sizing:border-box}
 #t{flex:1;padding:10px;border:1px solid #ccc;border-radius:10px;font-size:16px}
</style>
</head>
<body>
<header><b>Kaiwa Renshu</b><span><button onclick="mute()" id="m">🔊</button> <button onclick="reset()">↺</button></span></header>
<div id="chat"></div>
<div id="bar">
 <input id="t" autocomplete="off" placeholder="日本語で書いてね">
 <button onclick="toggleMic()" id="mic">🎤</button>
 <button onclick="send()">➤</button>
</div>
<script>
const chat = document.getElementById("chat"), t = document.getElementById("t");
let muted = false;
function add(cls, text){
  const d = document.createElement("div"); d.className = "msg " + cls; d.textContent = text; chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight; return d;
}
function jpnSentences(text){
  const joined = text.split("\n").filter(l => l.trim() && !l.startsWith("R:") && !l.startsWith("Koreksi")).join(" ");
  return (joined.match(/[^。！？]+[。！？]?/g) || []).filter(s => s.trim());
}
function fetchTTS(s){ return fetch("/tts?text=" + encodeURIComponent(s.trim())); }
function playAudio(blob){
  return new Promise(resolve => {
    if(window.hanaAudio) hanaAudio.pause();
    hanaAudio = new Audio(URL.createObjectURL(blob));
    hanaAudio.onended = resolve; hanaAudio.onerror = resolve;
    hanaAudio.play();
  });
}
async function speak(text){
  if(muted) return;
  const sents = jpnSentences(text);
  let cur = sents.length ? fetchTTS(sents[0]) : null, i = 1;
  while(cur){
    const p = cur;
    const nx = i < sents.length ? fetchTTS(sents[i++]) : null;
    try{
      const res = await p;
      if(res.ok) await playAudio(await res.blob());
    }catch(e){}
    cur = nx;
  }
}
function mute(){ muted = !muted; document.getElementById("m").textContent = muted ? "🔇" : "🔊"; if(muted) speechSynthesis.cancel(); }
let rec = null;
async function toggleMic(){
  const btn = document.getElementById("mic");
  if(rec && rec.state === "recording"){ rec.stop(); return; }
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const chunks = [];
    rec = new MediaRecorder(stream);
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach(x => x.stop());
      btn.textContent = "…";
      try{
        const fd = new FormData();
        fd.append("audio", new Blob(chunks, {type: rec.mimeType || "audio/webm"}), "speech.webm");
        const res = await fetch("/stt", {method: "POST", body: fd});
        const data = await res.json();
        if(data.text){ t.value = data.text; send(); }
        else if(data.error){ alert("STT: " + data.error); }
      }catch(e){ alert("[error] " + e); }
      finally{ btn.textContent = "🎤"; }
    };
    rec.start();
    btn.textContent = "⏹";
  }catch(e){ alert("[mic] " + e); }
}
async function send(){
  const text = t.value.trim(); if(!text) return; t.value = "";
  add("you", text);
  const h = add("hana", "…");
  try{
    const res = await fetch("/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({text})});
    const data = await res.json();
    h.textContent = data.reply || ("[error] " + data.error);
    if(data.reply) speak(data.reply);
  }catch(e){ h.textContent = "[error] " + e; }
}
async function reset(){ await fetch("/reset", {method:"POST"}); chat.innerHTML = ""; }
t.addEventListener("keydown", e => { if(e.key === "Enter") send(); });
add("hana", "はじめまして！Hana です。今日も いっしょに れんしゅう しよう！\\nR: Hajimemashite! Hana desu. Kyou mo issho ni renshuu shiyou!");
</script>
</body>
</html>"""


@app.get("/")
def index():
    return PAGE


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    print("=== Kaiwa Renshu server ===")
    print(f"Buka di HP (WiFi yang sama): http://{lan_ip()}:8000")
    app.run(host="0.0.0.0", port=8000)
