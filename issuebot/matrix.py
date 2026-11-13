"""Matrix-Anbindung (matrix-nio): Login, Sync, E2EE-Pflege, Einladungen, Senden.

Aufgebaut wie beim Musikbot, aber ohne Calls: nur Textbefehle lesen und Antworten schicken.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Optional

import nio

from . import cards
from .config import Config

log = logging.getLogger("issuebot.matrix")

SYNC_TIMEOUT_MS = 30_000

# room_id, sender, event_id, body, server_timestamp_ms
TextHandler = Callable[[str, str, str, str, int], Awaitable[None]]


class Matrix:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        os.makedirs(cfg.store_path, exist_ok=True)
        self.client = nio.AsyncClient(
            cfg.homeserver, cfg.user, device_id=cfg.device_id, store_path=cfg.store_path,
            config=nio.AsyncClientConfig(encryption_enabled=cfg.encryption_enabled,
                                         store_sync_tokens=True))
        self.on_text: Optional[TextHandler] = None
        self._key_req: set[str] = set()
        self._announced: set[str] = set()   # Raeume mit gesetzter Befehlsliste/Bot-Profil
        self._stop = asyncio.Event()
        self.client.add_event_callback(self._event_cb, nio.Event)

    # ------------------------------------------------------------------ Login
    async def login(self) -> None:
        cfg, c = self.cfg, self.client
        if cfg.token:
            c.restore_login(cfg.user, cfg.device_id, cfg.token)
            await self._whoami("Token")
            return
        # Token aus frueherem Passwort-Login wiederverwenden (sonst neues Geraet pro Neustart)
        token_file = os.path.join(cfg.store_path, "access_token")
        if os.path.exists(token_file):
            with open(token_file) as fh:
                saved = fh.read().strip()
            if saved:
                c.restore_login(cfg.user, cfg.device_id, saved)
                try:
                    await self._whoami("gespeicherter Token")
                    return
                except RuntimeError:
                    log.warning("Gespeicherter Token ungueltig, Passwort-Login")
        resp = await c.login(password=cfg.password, device_name="issuebot")
        if not isinstance(resp, nio.LoginResponse):
            raise RuntimeError(f"Login fehlgeschlagen: {resp}")
        cfg.matrix_user_id = resp.user_id
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(resp.access_token)
        log.info("Eingeloggt als %s (Geraet %s)", resp.user_id, resp.device_id)

    async def _whoami(self, how: str) -> None:
        me = await self.client.whoami()
        if not isinstance(me, nio.WhoamiResponse):
            raise RuntimeError(f"Login ({how}) ungueltig: {me}")
        self.cfg.matrix_user_id = me.user_id
        log.info("Eingeloggt als %s (%s)", me.user_id, how)

    @property
    def me(self) -> str:
        return self.cfg.matrix_user_id or self.cfg.user

    # ------------------------------------------------------------------ Sync
    async def first_sync(self) -> None:
        """Einmal synchronisieren, Raeume betreten, Befehlsliste anmelden."""
        resp = await self.client.sync(timeout=0, since=self.client.next_batch, full_state=True)
        if not isinstance(resp, nio.SyncResponse):
            raise RuntimeError(f"Erster Sync fehlgeschlagen: {resp}")
        await self._crypto_housekeeping()
        for spec in self.cfg.rooms:
            rid = await self._resolve(spec)
            if rid and rid not in self.client.rooms:
                await self._join(rid)
        await self._accept_invites()
        for rid in list(self.client.rooms):
            await self.announce(rid)

    async def run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                resp = await self.client.sync(timeout=SYNC_TIMEOUT_MS, since=self.client.next_batch)
            except Exception:
                log.exception("Sync-Fehler")
                resp = None
            if isinstance(resp, nio.SyncResponse):
                backoff = 1
                await self._crypto_housekeeping()
                await self._accept_invites()
                for rid in list(self.client.rooms):
                    if rid not in self._announced:
                        await self.announce(rid)
            else:
                if resp is not None:
                    log.warning("Sync-Fehler: %s", resp)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self.client.close()

    async def _crypto_housekeeping(self) -> None:
        """Was sync_forever() sonst macht: Schluessel hochladen/abfragen/claimen, To-Device senden."""
        c = self.client
        if not self.cfg.encryption_enabled or c.olm is None:
            return
        try:
            if c.should_upload_keys:
                await c.keys_upload()
            if c.should_query_keys:
                await c.keys_query()
            if c.should_claim_keys:
                await c.keys_claim(c.get_users_for_key_claiming())
            await c.send_to_device_messages()
        except Exception:
            log.exception("E2EE-Schluesselpflege fehlgeschlagen")

    # ------------------------------------------------------------------ Events
    async def _event_cb(self, room: nio.MatrixRoom, event) -> None:
        if getattr(event, "sender", None) == self.me and not isinstance(event, nio.PowerLevelsEvent):
            return
        if isinstance(event, nio.PowerLevelsEvent):
            # Rechte geaendert (z. B. Bot zum Moderator gemacht): Befehlsliste/Profil neu versuchen
            self._announced.discard(room.room_id)
            return
        if isinstance(event, nio.RoomMessageText):
            if self.on_text:
                try:
                    await self.on_text(room.room_id, event.sender, event.event_id,
                                       event.body or "", int(event.server_timestamp or 0))
                except Exception:
                    log.exception("Befehl in %s fehlgeschlagen", room.room_id)
        elif isinstance(event, nio.MegolmEvent):
            await self._request_room_key(event)

    async def _request_room_key(self, event: nio.MegolmEvent) -> None:
        """Fehlenden Raum-Schluessel beim Absender anfragen (nio macht das nicht selbst)."""
        sid = getattr(event, "session_id", None)
        if not sid or sid in self._key_req:
            return
        self._key_req.add(sid)
        try:
            resp = await self.client.to_device(event.as_key_request(event.sender, self.cfg.device_id))
            if isinstance(resp, nio.ErrorResponse):
                self._key_req.discard(sid)
                log.warning("Key-Request an %s fehlgeschlagen: %s", event.sender, resp)
            else:
                log.info("Raum-Key angefragt bei %s", event.sender)
        except Exception:
            self._key_req.discard(sid)
            log.exception("Key-Request fehlgeschlagen")

    # ------------------------------------------------------------------ Raeume
    def _invite_allowed(self, inviter: Optional[str]) -> bool:
        if not inviter:
            return False
        if self.cfg.allowed_users:
            return inviter in self.cfg.allowed_users
        servers = self.cfg.invite_servers or [self.cfg.server_name]
        return inviter.partition(":")[2] in servers

    async def _accept_invites(self) -> None:
        for room in list(self.client.invited_rooms.values()):
            inviter = getattr(room, "inviter", None)
            if self._invite_allowed(inviter):
                log.info("Einladung von %s in %s angenommen", inviter, room.room_id)
                await self._join(room.room_id)
            else:
                log.warning("Einladung von %s in %s abgelehnt", inviter, room.room_id)
                await self.client.room_leave(room.room_id)

    async def _join(self, room_id: str) -> None:
        resp = await self.client.join(room_id)
        if isinstance(resp, nio.JoinResponse):
            log.info("Raum beigetreten: %s", room_id)
        else:
            log.warning("Beitritt %s fehlgeschlagen: %s", room_id, resp)

    async def _resolve(self, spec: str) -> Optional[str]:
        if spec.startswith("!"):
            return spec
        resp = await self.client.room_resolve_alias(spec if spec.startswith("#") else f"#{spec}")
        if isinstance(resp, nio.RoomResolveAliasResponse):
            return resp.room_id
        log.error("Raum nicht gefunden: %s", spec)
        return None

    async def announce(self, room_id: str) -> None:
        """Befehle (Vorschlaege beim Tippen) und Bot-Profil fuer Diddy setzen. Fehlt das Recht
        (Moderator), bleibt es still: der Bot funktioniert trotzdem. Synapse legt bei gleichem
        Inhalt kein neues Event an, darum reicht einmal pro Raum und Start."""
        self._announced.add(room_id)
        for evtype, content in ((cards.COMMANDS_TYPE, cards.commands_state(self.cfg.prefix)),
                                (cards.BOT_TYPE, cards.BOT_PROFILE)):
            resp = await self.client.room_put_state(room_id, evtype, content, state_key=self.me)
            if isinstance(resp, nio.RoomPutStateResponse):
                log.info("%s in %s gesetzt", evtype, room_id)
            else:
                log.info("%s in %s nicht gesetzt (Rechte?): %s", evtype, room_id,
                         getattr(resp, "status_code", resp))

    # ------------------------------------------------------------------ Senden
    async def send(self, room_id: str, content: dict) -> Optional[str]:
        try:
            resp = await self.client.room_send(room_id, "m.room.message", content,
                                               ignore_unverified_devices=True)
        except Exception:
            log.exception("Senden in %s fehlgeschlagen", room_id)
            return None
        if isinstance(resp, nio.ErrorResponse):
            log.error("Senden in %s fehlgeschlagen: %s", room_id, resp)
            return None
        return getattr(resp, "event_id", None)

    def display_name(self, room_id: str, user_id: str) -> str:
        room = self.client.rooms.get(room_id)
        if room is None:
            return ""
        return room.user_name(user_id) or ""
