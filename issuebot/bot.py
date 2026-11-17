"""Bot-Logik: Chat-Befehl -> GitHub-Issue -> Antwortkarte. Gebaut auf der Bot-Library diddybot.

`build_bot()` liefert einen fertigen `diddybot.Bot`; Matrix, E2EE, Einladungen und das Diddy-Profil
uebernimmt die Library. Ohne Server testbar (`diddybot.testing.TestClient`).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

from diddybot import Bot, Context, cards
from diddybot.errors import CheckFailure

from .config import Config
from .github import CreatedIssue, GitHub, GitHubError
from .parse import KIND_LABEL, split_issue
from .store import Store

log = logging.getLogger("issuebot")

# Profilbild und Farben kommen vom Logo (branding/build.py). Die Library laedt das Bild beim Start hoch,
# aber nur, wenn sich die Datei geaendert hat.
AVATAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "avatar.png")
PROFILE = dict(about="Legt GitHub-Issues an: !issue Titel | Beschreibung", avatar=AVATAR,
               banner=("#34D6A0", "#047A55", 135), accent="#0F9D6E")

HELP_WORDS = ("", "help", "hilfe", "?")


def invite_filter(cfg: Config):
    """Einladungen nur von erlaubten Personen (ALLOWED_USERS) oder Servern (INVITE_SERVERS)."""
    def allowed(inviter: str, room_id: str) -> bool:
        if not inviter:
            return False
        if cfg.allowed_users:
            return inviter in cfg.allowed_users
        return inviter.partition(":")[2] in (cfg.invite_servers or [cfg.server_name])
    return allowed


def _short(text: str, limit: int = 50) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _md_escape(text: str) -> str:
    """Anzeigenamen sind fremde Eingaben: keine Links, Bilder, @-Erwaehnungen oder HTML im Issue."""
    text = " ".join((text or "").split())[:80]
    return "".join("\\" + ch if ch in "\\`*_{}[]()<>#!|~@" else ch for ch in text)


class IssueBot:
    """Haelt Konfiguration, GitHub, Speicher und KI zusammen und haengt die Befehle an den Bot."""

    def __init__(self, cfg: Config, github: GitHub, store: Store, researcher: Any = None,
                 *, bot: Optional[Bot] = None):
        self.cfg, self.github, self.store, self.researcher = cfg, github, store, researcher
        self.bot = bot or Bot(
            cfg.homeserver, cfg.user, password=cfg.password, access_token=cfg.token,
            device_id=cfg.device_id, store_path=cfg.store_path, prefix=cfg.prefix,
            encryption=cfg.encryption_enabled, auto_join=invite_filter(cfg),
            help_note=self._help_note(), help_command=False, **PROFILE)
        self._tasks: set[asyncio.Task] = set()
        self._register()
        if cfg.rooms:
            self.bot.listen("ready")(self._join_rooms)

    async def _join_rooms(self) -> None:
        """MATRIX_ROOMS: diese Raeume beim Start betreten (sonst reicht eine Einladung)."""
        import nio
        client = self.bot.client
        for spec in self.cfg.rooms:
            room = spec
            if not spec.startswith("!"):
                resp = await client.room_resolve_alias(spec if spec.startswith("#") else f"#{spec}")
                if not isinstance(resp, nio.RoomResolveAliasResponse):
                    log.error("Raum nicht gefunden: %s", spec)
                    continue
                room = resp.room_id
            if room not in client.rooms:
                resp = await client.join(room)
                log.info("Raum %s: %s", room, "beigetreten" if isinstance(resp, nio.JoinResponse)
                         else f"Beitritt fehlgeschlagen ({resp})")

    # ------------------------------------------------------------------ Befehle
    def _help_note(self) -> str:
        keys = list(self.cfg.repos)
        text = (f"{self.cfg.prefix}issue Titel | Beschreibung. Ohne | oder Zeilenumbruch wird ein kurzer Text "
                f"ganz zum Titel; bei langem Text ist der erste Satz der Titel. Ziel: "
                f"{self.cfg.repos[keys[0]]}.")
        if len(keys) > 1:
            text += " Anderes Repo: " + ", ".join(f"{self.cfg.prefix}issue {k}: …" for k in keys[1:]) + "."
        return text

    def _register(self) -> None:
        bot, p = self.bot, self.cfg.prefix
        if self.cfg.allowed_users:
            @bot.check
            async def allowed(ctx: Context) -> bool:
                if ctx.sender not in self.cfg.allowed_users:
                    raise CheckFailure("Du darfst mit diesem Bot keine Issues anlegen.")
                return True

        def make(kind: str) -> Any:
            async def run(ctx: Context) -> None:
                await self._create(ctx, kind)
            return run

        specs = (("issue", "issue", ("ticket", "problem"), "Issue auf GitHub anlegen"),
                 ("bug", "bug", ("fehler",), "Fehler melden (Label bug)"),
                 ("idee", "idea", ("idea", "feature", "wunsch"), "Idee/Wunsch (Label enhancement)"))
        for name, kind, aliases, desc in specs:
            bot.command(name, desc=desc, usage=f"{p}{name} <Titel> | <Beschreibung>",
                        aliases=aliases, group="Issue melden")(make(kind))

        @bot.command("issuebot", desc="Hilfe zum Issue-Bot", aliases=("issuehilfe", "issuehelp"),
                     group="Hilfe")
        async def issuebot(ctx: Context) -> None:
            await ctx.reply(bot.registry.help_card(bot.help_note))

    # ------------------------------------------------------------------ Issue
    async def _create(self, ctx: Context, kind: str) -> None:
        cfg = self.cfg
        if ctx.arg.strip().lower() in HELP_WORDS:
            await ctx.reply(self.bot.registry.help_card(self.bot.help_note))
            return
        if not self.store.claim(ctx.event_id):
            return
        draft = split_issue(ctx.arg, cfg.repos.keys())
        if not draft.title:
            await self._say(ctx, f"Titel fehlt. So geht's: {cfg.prefix}issue Titel | Beschreibung", "error")
            return

        used = self.store.recent_count(ctx.sender, cfg.rate_seconds)
        if cfg.rate_count and used >= cfg.rate_count:
            oldest = self.store.oldest_in_window(ctx.sender, cfg.rate_seconds) or time.time()
            wait_min = max(1, int((oldest + cfg.rate_seconds - time.time() + 59) // 60))
            await self._say(ctx, f"Zu viele Issues auf einmal. Versuch es in {wait_min} Min. wieder.",
                            "warning")
            return

        repo = cfg.repos[draft.repo_key or cfg.default_repo_key]
        labels = list(cfg.labels)
        extra = KIND_LABEL.get(kind)
        if extra and extra not in labels:
            labels.append(extra)
        body = self._issue_body(ctx, draft.body)

        try:
            issue: CreatedIssue = await self.github.create_issue(repo, draft.title, body, labels)
        except GitHubError as exc:
            await self._say(ctx, str(exc), "error")
            return
        self.store.record_issue(ctx.event_id, ctx.sender, ctx.room_id, repo, issue.number, issue.url)
        log.info("Issue %s#%s von %s angelegt", repo, issue.number, ctx.sender)
        if self.researcher is not None:
            task = asyncio.create_task(self._research(repo, issue.number))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        where = "" if repo == cfg.repos[cfg.default_repo_key] else f" in {repo.split('/')[-1]}"
        await ctx.reply(cards.note(f"#{issue.number} angelegt{where}: {_short(issue.title)}",
                                   tone="success", icon="✅", url=issue.url, link_label="Issue öffnen"),
                        quote=True)

    async def _say(self, ctx: Context, text: str, tone: str) -> None:
        await ctx.reply(cards.note(text, tone=tone, icon="⏳" if tone == "warning" else "⚠️"), quote=True)

    async def _research(self, repo: str, number: int) -> None:
        """Im Hintergrund: KI recherchiert und bereitet das Issue auf. Fehler nur ins Log."""
        try:
            await asyncio.wait_for(self.researcher.run(repo, number), self.cfg.ai_timeout * 3)
        except Exception as exc:   # noqa: BLE001 - nie den Bot stoeren
            log.warning("KI-Recherche fuer %s#%s fehlgeschlagen: %s", repo, number, exc, exc_info=True)

    def _issue_body(self, ctx: Context, description: str) -> str:
        parts = [description.strip() or "_Keine Beschreibung._"]
        mode = self.cfg.reporter
        if mode != "off":
            if mode == "id":
                who = f"`{ctx.sender}`"
            else:
                name = _md_escape(ctx.author.name)
                who = f"{name} (`{ctx.sender}`)" if name and name != ctx.sender else f"`{ctx.sender}`"
            parts.append(f"---\n<sub>Gemeldet über Matrix von {who}.</sub>")
        return "\n\n".join(parts)
