# Hana — Kaiwa Renshu

Minimal web app for practicing Japanese conversation (会話練習) with an AI partner named **Hana**. She replies in simple Japanese with romaji, and corrects your mistakes in Indonesian.

Built for personal use: runs 24/7 in Docker on a home mini PC, reachable from your phone via Cloudflare Tunnel.

## Features

- Japanese conversation practice, tuned for beginner/intermediate (JLPT N4)
- Romaji under every reply, corrections in Indonesian
- Japanese text-to-speech in the browser (Web Speech API)
- Chat logs saved to `logs/` for Anki sentence mining
- Single-file Flask app, OpenAI-compatible LLM API

## Setup

1. Put your API key in `key.txt` (next to `app.py`)
2. Adjust `API_URL` / `MODELS` in `app.py` if you use a different OpenAI-compatible endpoint
3. Run:

```bash
# local
python app.py          # needs: pip install flask requests

# or Docker
docker compose up -d --build
```

Open `http://localhost:8000` — from your phone, use your PC's LAN IP or a Cloudflare Tunnel.

## Deploy to a remote mini PC (optional)

`deploy.py` copies the app over SSH and starts it with Docker Compose (also manages the Cloudflare Tunnel ingress + DNS route):

```bash
python deploy.py --host <ip> --user <user> --pw <password> deploy
```

## Notes

- `key.txt` is mounted into the container, never baked into the image
- No auth on the web page by design (LAN/tunnel use) — add one before exposing publicly
