#!/usr/bin/env python3
"""Génère un résumé IA (API Anthropic, modèle Haiku) pour chaque fil de discussion.

- Lit docs/data/messages.json (produit par scrape.py).
- Regroupe les messages en fils (même logique que le site).
- Ne résume que les fils nouveaux ou modifiés (cache docs/data/summaries.json).
- Nécessite la variable d'environnement ANTHROPIC_API_KEY.

Usage : python scraper/summarize.py
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
MESSAGES = DATA_DIR / "messages.json"
SUMMARIES = DATA_DIR / "summaries.json"

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
MAX_THREAD_CHARS = 9000   # texte max envoyé par fil
DELAY = 0.3               # pause entre deux appels API

# --- regroupement en fils : doit rester IDENTIQUE à la logique JS du site ---

PREFIX = re.compile(r"^(\[[^\]]*\]|(re|fwd|fw|tr|rep|rép)\s*:)\s*", re.IGNORECASE)


def clean_subject(s):
    out = (s or "").strip()
    while True:
        new = PREFIX.sub("", out, count=1)
        if new == out:
            break
        out = new
    return out or "(sans sujet)"


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def thread_key(subject):
    return re.sub(r"\s+", " ", norm(clean_subject(subject))).strip()


# ---------------------------------------------------------------- résumés ---

def build_threads(messages):
    threads = {}
    for m in messages:
        threads.setdefault(thread_key(m["s"]), []).append(m)
    for msgs in threads.values():
        msgs.sort(key=lambda m: m.get("d") or "")
    return threads


def thread_text(msgs):
    parts = [f"Sujet : {clean_subject(msgs[0]['s'])}"]
    budget = MAX_THREAD_CHARS
    for m in msgs:
        body = (m.get("b") or "").strip()
        chunk = f"\n--- Message de {m.get('a', '?')} ({(m.get('d') or '')[:10]}) ---\n{body}"
        if len(chunk) > budget:
            chunk = chunk[:budget] + "…"
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    return "\n".join(parts)


def summarize(api_key, text, n_msgs):
    prompt = (
        "Voici une conversation de la liste de discussion RGAA (accessibilité "
        "numérique, France). Résume-la en français, en 2 phrases maximum : "
        "1) la question ou le sujet posé ; 2) la réponse, la solution ou le "
        "consensus qui se dégage des échanges (s'il y en a un). "
        "Sois factuel, concis, sans introduction ni guillemets. "
        f"La conversation compte {n_msgs} message(s).\n\n" + text
    )
    r = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    if r.status_code == 429:  # rate limit : on attend et on retente une fois
        time.sleep(30)
        return summarize(api_key, text, n_msgs)
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY absente : résumés ignorés.")
        return

    messages = json.loads(MESSAGES.read_text(encoding="utf-8"))["messages"]
    threads = build_threads(messages)
    cache = {}
    if SUMMARIES.exists():
        cache = json.loads(SUMMARIES.read_text(encoding="utf-8"))

    todo = {k: v for k, v in threads.items()
            if k not in cache or cache[k].get("n") != len(v)}
    print(f"{len(threads)} fils, {len(todo)} à résumer.")

    done, errors = 0, 0
    for key, msgs in todo.items():
        try:
            summary = summarize(api_key, thread_text(msgs), len(msgs))
            cache[key] = {"s": summary, "n": len(msgs)}
            done += 1
        except Exception as e:
            errors += 1
            print(f"  ! erreur sur « {key[:60]} » : {e}", file=sys.stderr)
            if errors > 20:
                print("Trop d'erreurs, arrêt.", file=sys.stderr)
                break
        # sauvegarde régulière pour ne rien perdre en cas d'interruption
        if done % 25 == 0:
            SUMMARIES.write_text(
                json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8")
        time.sleep(DELAY)

    # purge des fils disparus + écriture finale
    cache = {k: v for k, v in cache.items() if k in threads}
    SUMMARIES.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"Terminé : {done} résumés générés, {errors} erreurs, "
          f"{len(cache)} au total.")


if __name__ == "__main__":
    main()
