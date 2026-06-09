#!/usr/bin/env python3
"""Scraper des archives publiques de la liste de discussion RGAA (Sympa/MHonArc, Renater).

Usage :
    python scraper/scrape.py            # incrémental : nouveaux mois + les 2 derniers mois
    python scraper/scrape.py --full     # récupération complète de l'historique
    python scraper/scrape.py --months 2026-05 2026-06   # mois précis

Les données sont stockées dans docs/data/months/AAAA-MM.json (un fichier par mois),
puis combinées dans docs/data/messages.json (consommé par le site).
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://groupes.renater.fr/sympa/arc/rgaa"
HEADERS = {
    "User-Agent": "rgaa-archive-search/1.0 (miroir de recherche non commercial)"
}
DELAY = 0.6  # secondes entre deux requêtes (politesse)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
MONTHS_DIR = DATA_DIR / "months"
MAX_BODY = 30000  # caractères max conservés par message

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url, retries=3):
    """GET avec retries. Retourne le HTML ou None si 404."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            time.sleep(DELAY)
            return r.text
        except requests.RequestException as e:
            wait = 5 * (attempt + 1)
            print(f"  ! erreur sur {url} ({e}), nouvel essai dans {wait}s", file=sys.stderr)
            time.sleep(wait)
    print(f"  !! abandon : {url}", file=sys.stderr)
    return None


def list_months():
    """Liste des mois disponibles (AAAA-MM) depuis la page d'index des archives."""
    html = fetch(BASE)
    if not html:
        sys.exit("Impossible de charger l'index des archives.")
    months = sorted(set(re.findall(r"arc/rgaa/(\d{4}-\d{2})/", html)))
    return months


def list_message_ids(month):
    """IDs des messages d'un mois (msgNNNNN) via les pages chronologiques mail*.html."""
    ids = set()
    page = 1
    while True:
        html = fetch(f"{BASE}/{month}/mail{page}.html")
        if html is None:
            break
        found = set(re.findall(r'href="(msg\d+)\.html"', html))
        if not found - ids and page > 1:
            break
        ids |= found
        # pagination : existe-t-il une page suivante ?
        if f"mail{page + 1}.html" not in html:
            break
        page += 1
    return sorted(ids)


# ---------------------------------------------------------------- parsing ----

META_LABELS = ("from", "subject", "date")


def _clean_author(raw):
    """'\"Jean Dupont\" <adresse@cachée>' -> 'Jean Dupont'"""
    raw = re.sub(r"<[^>]*>", "", raw)
    return raw.strip().strip('"').strip() or "Inconnu"


def _parse_date(raw):
    try:
        return parsedate_to_datetime(raw.strip()).isoformat()
    except Exception:
        return None


def parse_message(html, month, msg_id):
    """Extrait sujet, auteur, date et corps d'une page message Sympa/MHonArc.

    Deux stratégies :
    1. les commentaires MHonArc <!--X-Body-of-Message--> ... (si présents) ;
    2. la structure visible : liste de métadonnées (From/Subject/Date),
       puis le corps entre les deux <hr> qui suivent.
    """
    soup = BeautifulSoup(html, "html.parser")
    msg = {"id": f"{month}/{msg_id}", "s": "", "a": "", "d": None, "b": ""}

    # --- métadonnées : commentaires MHonArc d'abord
    m = re.search(r"<!--X-Subject:\s*(.*?)\s*-->", html, re.S)
    if m:
        msg["s"] = BeautifulSoup(m.group(1), "html.parser").get_text().strip()
    m = re.search(r"<!--X-Date:\s*(.*?)\s*-->", html, re.S)
    if m:
        msg["d"] = _parse_date(BeautifulSoup(m.group(1), "html.parser").get_text())

    # --- métadonnées : structure visible (From/Subject/Date dans une liste)
    meta_block = None
    for el in soup.find_all(["li", "dt", "p"]):
        txt = el.get_text(" ", strip=True)
        low = txt.lower()
        for label in META_LABELS:
            if low.startswith(label) and ":" in txt:
                value = txt.split(":", 1)[1].strip()
                if label == "from" and not msg["a"]:
                    msg["a"] = _clean_author(value)
                    meta_block = el.find_parent(["ul", "dl"]) or el
                elif label == "subject" and not msg["s"]:
                    msg["s"] = value
                elif label == "date" and not msg["d"]:
                    msg["d"] = _parse_date(value)
                break

    # --- corps : marqueurs MHonArc
    m = re.search(
        r"<!--X-Body-of-Message-->(.*?)<!--X-Body-of-Message-End-->", html, re.S
    )
    if m:
        body = BeautifulSoup(m.group(1), "html.parser").get_text("\n")
    else:
        # --- corps : fallback structurel (entre les 2 <hr> après les métadonnées)
        body = ""
        if meta_block is not None:
            parts, hr_seen, captured = [], 0, set()
            for el in meta_block.find_all_next():
                if el.name == "hr":
                    hr_seen += 1
                    if hr_seen >= 2:
                        break
                    continue
                if hr_seen == 1 and el.name in ("p", "pre", "blockquote", "div", "li"):
                    if any(parent in captured for parent in el.parents):
                        continue  # déjà inclus via un ancêtre
                    # éviter l'index de fil (liens vers msg*.html)
                    if el.find("a", href=re.compile(r"msg\d+\.html")):
                        break
                    captured.add(el)
                    parts.append(el.get_text("\n"))
            body = "\n".join(parts)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    msg["b"] = body[:MAX_BODY]
    msg["s"] = msg["s"] or "(sans sujet)"
    msg["a"] = msg["a"] or "Inconnu"
    return msg


# ---------------------------------------------------------------- scraping ---

def scrape_month(month):
    """Scrape un mois complet, retourne la liste des messages."""
    ids = list_message_ids(month)
    print(f"[{month}] {len(ids)} messages")
    messages = []
    for msg_id in ids:
        html = fetch(f"{BASE}/{month}/{msg_id}.html")
        if html is None:
            continue
        messages.append(parse_message(html, month, msg_id))
    return messages


def build_index():
    """Combine les fichiers mensuels en docs/data/messages.json."""
    all_msgs = []
    for f in sorted(MONTHS_DIR.glob("*.json")):
        all_msgs.extend(json.loads(f.read_text(encoding="utf-8")))
    all_msgs.sort(key=lambda x: x.get("d") or "", reverse=True)
    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(all_msgs),
        "messages": all_msgs,
    }
    target = DATA_DIR / "messages.json"
    target.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"Index : {len(all_msgs)} messages -> {target}")
    return all_msgs


def validate(messages, full_run):
    """Contrôle qualité : alerte si trop de corps vides ou de dates manquantes."""
    if not messages:
        sys.exit("Aucun message récupéré : abandon.")
    empty = sum(1 for m in messages if not m["b"])
    nodate = sum(1 for m in messages if not m["d"])
    print(f"Validation : {empty}/{len(messages)} corps vides, {nodate} dates manquantes")
    if full_run and empty / len(messages) > 0.2:
        sys.exit(
            "Plus de 20 % de messages sans corps : le format des pages a "
            "probablement changé. Vérifier parse_message(). Abandon avant commit."
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="tout récupérer")
    ap.add_argument("--months", nargs="*", help="mois précis (AAAA-MM)")
    args = ap.parse_args()

    MONTHS_DIR.mkdir(parents=True, exist_ok=True)
    available = list_months()
    print(f"{len(available)} mois disponibles sur le serveur")

    if args.months:
        todo = [m for m in args.months if m in available]
    elif args.full:
        todo = available
    else:
        # incrémental : mois jamais scrapés + les 2 derniers (messages tardifs)
        done = {f.stem for f in MONTHS_DIR.glob("*.json")}
        todo = [m for m in available if m not in done] + available[-2:]
        todo = sorted(set(todo))

    print(f"À scraper : {', '.join(todo)}")
    for month in todo:
        messages = scrape_month(month)
        if messages:
            (MONTHS_DIR / f"{month}.json").write_text(
                json.dumps(messages, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

    all_msgs = build_index()
    validate(all_msgs, args.full)
    print("Terminé.")


if __name__ == "__main__":
    main()
