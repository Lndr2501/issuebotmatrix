"""Bot-Logik: Chat-Befehl -> GitHub-Issue -> Antwortkarte. Ohne nio testbar (Matrix wird uebergeben)."""
from __future__ import annotations

import logging
import time
from typing import Optional, Protocol

from . import cards
from .config import Config
from .github import CreatedIssue, GitHub, GitHubError
from .parse import KIND_LABEL, parse_command, split_issue
from .store import Store

log = logging.getLogger("issuebot")


class MatrixLike(Protocol):
    async def send(self, room_id: str, content: dict) -> Optional[str]: ...
    def display_name(self, room_id: str, user_id: str) -> str: ...


class Bot:
    def __init__(self, cfg: Config, matrix: MatrixLike, github: GitHub, store: Store):
        self.cfg = cfg
        self.matrix = matrix
        self.github = github
        self.store = store
        self.started_ms = int(time.time() * 1000)

    # ------------------------------------------------------------------ Eingang
    async def on_text(self, room_id: str, sender: str, event_id: str, body: str,
                      server_ts_ms: int) -> None:
        cmd = parse_command(body, self.cfg.prefix)
        if cmd is None:
            return
        # Nachrichten von vor dem Start (erster Sync nach Neustart/Neuanmeldung) nie ausfuehren
        if server_ts_ms and server_ts_ms < self.started_ms - 5_000:
            log.info("Alter Befehl %s ignoriert", event_id)
            return
        if not self.store.claim(event_id):
            return
        if self.cfg.allowed_users and sender not in self.cfg.allowed_users:
            await self.matrix.send(room_id, cards.error(
                "Du darfst mit diesem Bot keine Issues anlegen.", event_id))
            return
        if cmd.kind == "help":
            await self.matrix.send(room_id, cards.help_message(self.cfg.prefix, self.cfg.repos))
            return
        await self._create(room_id, sender, event_id, cmd.kind, cmd.arg)

    # ------------------------------------------------------------------ Issue
    async def _create(self, room_id: str, sender: str, event_id: str, kind: str, arg: str) -> None:
        cfg = self.cfg
        draft = split_issue(arg, cfg.repos.keys())
        if not draft.title:
            await self.matrix.send(room_id, cards.error(
                f"Titel fehlt. So geht's: {cfg.prefix}issue Titel | Beschreibung", event_id))
            return

        used = self.store.recent_count(sender, cfg.rate_seconds)
        if cfg.rate_count and used >= cfg.rate_count:
            oldest = self.store.oldest_in_window(sender, cfg.rate_seconds) or time.time()
            wait_min = max(1, int((oldest + cfg.rate_seconds - time.time() + 59) // 60))
            await self.matrix.send(room_id, cards.warning(
                f"Zu viele Issues auf einmal. Versuch es in {wait_min} Min. wieder.", event_id))
            return

        repo = cfg.repos[draft.repo_key or cfg.default_repo_key]
        labels = list(cfg.labels)
        extra = KIND_LABEL.get(kind)
        if extra and extra not in labels:
            labels.append(extra)
        body = self._issue_body(room_id, sender, draft.body)

        try:
            issue: CreatedIssue = await self.github.create_issue(repo, draft.title, body, labels)
        except GitHubError as exc:
            await self.matrix.send(room_id, cards.error(str(exc), event_id))
            return
        self.store.record_issue(event_id, sender, room_id, repo, issue.number, issue.url)
        log.info("Issue %s#%s von %s angelegt", repo, issue.number, sender)
        shown_repo = "" if repo == cfg.repos[cfg.default_repo_key] else repo
        await self.matrix.send(room_id, cards.created(
            issue.number, issue.title, issue.url, shown_repo, event_id))

    def _issue_body(self, room_id: str, sender: str, description: str) -> str:
        parts = [description.strip() or "_Keine Beschreibung._"]
        mode = self.cfg.reporter
        if mode != "off":
            if mode == "id":
                who = f"`{sender}`"
            else:
                name = _md_escape(self.matrix.display_name(room_id, sender))
                who = f"{name} (`{sender}`)" if name and name != sender else f"`{sender}`"
            parts.append(f"---\n<sub>Gemeldet über Matrix von {who}.</sub>")
        return "\n\n".join(parts)


def _md_escape(text: str) -> str:
    """Anzeigenamen sind fremde Eingaben: keine Links, Bilder, @-Erwaehnungen oder HTML im Issue."""
    text = " ".join((text or "").split())[:80]
    out = []
    for ch in text:
        if ch in "\\`*_{}[]()<>#!|~@":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)
