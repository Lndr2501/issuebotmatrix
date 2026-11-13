"""Befehle aus Chat-Text lesen. Rein (kein nio), damit alles ohne Matrix testbar ist.

    !issue Titel | Beschreibung
    !issue Titel                 (Zeilenumbruch mit Shift+Enter)
    Beschreibung ...
    !issue "Titel mit Leerzeichen" Beschreibung
    !issue Ein langer Satz. Noch mehr Text ...   (Titel = erster Satz, Rest = Beschreibung)
    !bug musik: Titel | Beschreibung              (anderes Repo per Kurzname)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

TITLE_MAX = 120          # GitHub erlaubt mehr, im Chat und in Listen liest sich das aber schlecht
SHORT_TITLE = 80         # bis zu dieser Laenge ist ein einzeiliger Text komplett der Titel
BODY_MAX = 60_000        # GitHub-Grenze liegt bei 65536 Zeichen

# Befehl -> Art des Issues (bestimmt das zusaetzliche Label)
COMMANDS = {
    "issue": "issue", "ticket": "issue", "problem": "issue",
    "bug": "bug", "fehler": "bug",
    "idee": "idea", "idea": "idea", "feature": "idea", "wunsch": "idea",
}
KIND_LABEL = {"issue": None, "bug": "bug", "idea": "enhancement"}

_QUOTES = {'"': '"', "„": "“", "“": "”", "”": "”", "'": "'", "«": "»", "»": "«", "‚": "‘"}
_REPO_PREFIX = re.compile(r"^([A-Za-z0-9_-]+):\s+")
_SENTENCE_END = re.compile(r"[.!?](\s|$)")


@dataclass
class Command:
    kind: str                 # issue | bug | idea | help
    arg: str = ""


@dataclass
class IssueDraft:
    title: str
    body: str = ""
    repo_key: Optional[str] = None


def strip_reply_fallback(body: str) -> str:
    """Element (alt) setzt bei Antworten das Zitat als '> ...'-Zeilen vor den Text."""
    lines = (body or "").split("\n")
    if not lines or not lines[0].startswith("> "):
        return body or ""
    i = 0
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:])


def parse_command(text: str, prefix: str = "!") -> Optional[Command]:
    text = strip_reply_fallback(text).strip()
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):]
    m = re.match(r"([A-Za-zÄÖÜäöü]+)(?:\s+|$)", rest)
    if not m:
        return None
    name = m.group(1).lower()
    if name in ("issuebot", "issuehilfe", "issuehelp"):
        return Command("help")
    kind = COMMANDS.get(name)
    if kind is None:
        return None
    arg = rest[m.end():].strip()
    if arg.lower() in ("", "help", "hilfe", "?"):
        return Command("help")
    return Command(kind, arg)


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"


def split_issue(arg: str, repo_keys=()) -> IssueDraft:
    """Titel und Beschreibung aus dem Text nach dem Befehl trennen."""
    text = arg.strip()
    repo_key = None
    m = _REPO_PREFIX.match(text)
    if m and m.group(1).lower() in {k.lower() for k in repo_keys}:
        repo_key = m.group(1).lower()
        text = text[m.end():].strip()

    title, body = "", ""
    first, nl, after = text.partition("\n")
    if nl and first.strip():
        title, body = first, after
        # "!issue Titel | Beschreibung" auch in der ersten Zeile erlauben
        if "|" in title:
            t, _, b = title.partition("|")
            title, body = t, (b.strip() + "\n" + body).strip()
    elif text[:1] in _QUOTES and _QUOTES[text[0]] in text[1:]:
        end = text.index(_QUOTES[text[0]], 1)
        title, body = text[1:end], text[end + 1:]
    elif "|" in text:
        title, _, body = text.partition("|")
    elif len(text) <= SHORT_TITLE:
        title = text
    else:
        m2 = _SENTENCE_END.search(text)
        if m2 and m2.end() <= TITLE_MAX:
            title, body = text[:m2.start() + (0 if text[m2.start()] == "." else 1)], text[m2.end():]
        else:
            title, body = _cut(text, SHORT_TITLE), text   # ganzer Text bleibt in der Beschreibung

    title = _cut(title.strip(" \t|-–:"), TITLE_MAX)
    body = body.strip()
    if not title and body:          # z. B. "!issue | nur Beschreibung"
        title, body = _cut(body.split("\n")[0], SHORT_TITLE), body
    return IssueDraft(title=title, body=body[:BODY_MAX], repo_key=repo_key)
