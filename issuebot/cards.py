"""Diddy-Karten (dev.diddy.card), Befehlsliste (dev.diddy.commands) und Bot-Profil (dev.diddy.bot).

Protokoll: docs/bot-cards.md im Diddy-Repo. Jede Nachricht behaelt einen lesbaren `body` fuer
Element & Co.; Diddy zeichnet aus dem Zusatzfeld die Karte. Rein (kein nio).
"""
from __future__ import annotations

from typing import Optional

CARD_KEY = "dev.diddy.card"
COMMANDS_TYPE = "dev.diddy.commands"
BOT_TYPE = "dev.diddy.bot"
VERSION = 1


def _clean(card: dict) -> dict:
    out = {k: v for k, v in card.items() if v not in (None, "", [], {})}
    out["v"] = VERSION
    return out


def message(body: str, card: dict, reply_to: Optional[str] = None) -> dict:
    content: dict = {"msgtype": "m.notice", "body": body, CARD_KEY: _clean(card)}
    if reply_to:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}
    return content


def note(text: str, tone: str = "info", icon: str = "", url: str = "") -> dict:
    """Hinweis-Karte. `url` zeigt Diddy als Link, sobald note-Karten Links koennen
    (aeltere Diddy-Versionen ignorieren das Feld; der Link steht dann im body)."""
    assert tone in ("info", "success", "warning", "error"), tone
    return {"kind": "note", "text": text, "tone": tone, "icon": icon or None, "url": url or None}


def created(number: int, title: str, url: str, repo: str, reply_to: Optional[str]) -> dict:
    text = f"Issue #{number} in {repo} angelegt: {title}"
    return message(f"✅ {text}\n{url}", note(text, "success", "✅", url), reply_to)


def error(text: str, reply_to: Optional[str] = None) -> dict:
    return message(f"⚠️ {text}", note(text, "error", "⚠️"), reply_to)


def warning(text: str, reply_to: Optional[str] = None) -> dict:
    return message(f"⏳ {text}", note(text, "warning", "⏳"), reply_to)


def _rows(*rows: tuple[str, str]) -> list[dict]:
    return [{"usage": u, "desc": d} for u, d in rows]


def help_message(prefix: str, repos: dict[str, str]) -> dict:
    p = prefix
    keys = list(repos)
    groups = [
        {"title": "Issue melden", "items": _rows(
            (f"{p}issue Titel | Beschreibung", "Issue anlegen"),
            (f"{p}issue Titel ⇧↵ Beschreibung", "Titel in Zeile 1, Beschreibung darunter (Shift+Enter)"),
            (f'{p}issue "Titel" Beschreibung', "Titel in Anführungszeichen"),
            (f"{p}bug … · {p}idee …", "wie !issue, mit Label bug bzw. enhancement"),
        )},
    ]
    if len(keys) > 1:
        groups.append({"title": "Repo wählen", "items": _rows(
            *[(f"{p}issue {k}: Titel | …", repos[k] + (" (Standard)" if i == 0 else ""))
              for i, k in enumerate(keys)])})
    text = (f"Ohne | oder Zeilenumbruch wird ein kurzer Text ganz zum Titel; bei langem Text ist der "
            f"erste Satz der Titel. Ziel: {repos[keys[0]]}.")
    body_lines = [f"{p}issue Titel | Beschreibung  – Issue anlegen",
                  f"{p}bug … / {p}idee …  – mit Label bug / enhancement"]
    if len(keys) > 1:
        body_lines.append("Repo wählen: " + ", ".join(f"{p}issue {k}: …" for k in keys))
    return message("\n".join(body_lines), {"kind": "help", "groups": groups, "note": text})


def commands_state(prefix: str) -> dict:
    """Inhalt fuer dev.diddy.commands (Vorschlaege beim Tippen)."""
    p = prefix
    return {
        "v": VERSION,
        "prefix": p,
        "commands": [
            {"name": "issue", "usage": f"{p}issue <Titel> | <Beschreibung>", "desc": "Issue auf GitHub anlegen"},
            {"name": "bug", "usage": f"{p}bug <Titel> | <Beschreibung>", "desc": "Fehler melden (Label bug)"},
            {"name": "idee", "usage": f"{p}idee <Titel> | <Beschreibung>", "desc": "Idee/Wunsch (Label enhancement)"},
            {"name": "issuebot", "usage": f"{p}issuebot", "desc": "Hilfe zum Issue-Bot"},
        ],
    }


BOT_PROFILE = {
    "v": VERSION,
    "about": "Legt GitHub-Issues an: !issue Titel | Beschreibung",
    "banner": {"from": "#f97316", "to": "#7a5cff", "angle": 135},
    "accent": "#f97316",
}
