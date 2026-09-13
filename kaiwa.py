import sys
from datetime import datetime
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
KEY_FILE = BASE / "key.txt"
LOG_DIR = BASE / "logs"
MODEL = "gemini-2.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SYSTEM = """You are Hana, a friendly Japanese conversation partner for an Indonesian learner (around JLPT N4). The goal is kaiwa renshu (conversation practice).

Rules:
- Chat about everyday topics and ask follow-up questions to keep the conversation going.
- Reply in simple natural Japanese, 3-5 sentences max. After each Japanese sentence, add its romaji in parentheses.
- If the user's Japanese has mistakes, reply naturally first, then add a short "Koreksi:" section in Indonesian (salah -> benar + alasan singkat).
- If the user writes in Indonesian or English, gently encourage them to try in Japanese and show how their sentence is said in Japanese (with romaji).
- Stay in character; be warm and encouraging."""


def load_key():
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    print("Letakkan API key Gemini kamu di file:", KEY_FILE)
    print("Ambil gratis di: https://aistudio.google.com/apikey")
    sys.exit(1)


def ask(history, key):
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": history,
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 1000,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    r = requests.post(URL, params={"key": key}, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError("Jawaban tidak bisa dibaca: " + str(data)[:300])


def main():
    key = load_key()
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / (datetime.now().strftime("%Y-%m-%d_%H%M") + ".md")
    history = []
    print("=== Kaiwa Renshu (chat dengan Hana) ===")
    print("Tulis pakai bahasa Jepang sebisa mungkin. /quit untuk keluar.")
    print("Log disimpan ke:", log_path.name)
    while True:
        try:
            user = input("\nKamu > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not user:
            continue
        if user.lower() in ("/quit", "/exit", "/q"):
            break
        history.append({"role": "user", "parts": [{"text": user}]})
        try:
            reply = ask(history, key)
        except (requests.RequestException, RuntimeError) as e:
            print("\n[error]", e)
            history.pop()
            continue
        history.append({"role": "model", "parts": [{"text": reply}]})
        print("\nHana > " + reply)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"## Kamu\n\n{user}\n\n## Hana\n\n{reply}\n\n")
    print("\nSampai jumpa! Log:", log_path)


if __name__ == "__main__":
    main()
