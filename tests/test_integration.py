"""Ende zu Ende gegen einen echten Homeserver, in einem verschluesselten Raum (nur mit
DIDDY_TEST_HOMESERVER, z. B. einem lokalen Synapse mit offener Registrierung)::

    DIDDY_TEST_HOMESERVER=http://127.0.0.1:8008 pytest tests/test_integration.py
"""
import asyncio
import json
import os
import secrets
import urllib.request

import pytest

HS = os.environ.get("DIDDY_TEST_HOMESERVER", "")
pytestmark = pytest.mark.skipif(not HS, reason="DIDDY_TEST_HOMESERVER nicht gesetzt")

if HS:
    import nio

    from issuebot.bot import IssueBot
    from issuebot.config import Config
    from issuebot.github import CreatedIssue
    from issuebot.store import Store


def register(name: str, password: str) -> str:
    body = json.dumps({"username": name, "password": password,
                       "auth": {"type": "m.login.dummy"}}).encode()
    req = urllib.request.Request(f"{HS}/_matrix/client/v3/register", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["user_id"]


class User:
    """A person with a normal E2EE client (what Diddy does, minus the drawing)."""

    def __init__(self, name, password, store):
        os.makedirs(store, exist_ok=True)
        self.c = nio.AsyncClient(HS, name, store_path=store,
                                 config=nio.AsyncClientConfig(encryption_enabled=True))
        self.password = password
        self.events = []
        self.c.add_event_callback(self._on, nio.Event)

    async def _on(self, room, event):
        self.events.append((room.room_id, event))

    async def login(self):
        r = await self.c.login(self.password)
        assert isinstance(r, nio.LoginResponse), r
        await self.sync()

    async def sync(self, timeout=0):
        await self.c.sync(timeout=timeout, full_state=True)
        if self.c.should_upload_keys:
            await self.c.keys_upload()
        if self.c.should_query_keys:
            await self.c.keys_query()
        if self.c.should_claim_keys:
            await self.c.keys_claim(self.c.get_users_for_key_claiming())
        await self.c.send_to_device_messages()

    async def wait_for(self, pred, seconds=20):
        for _ in range(int(seconds * 4)):
            for room_id, ev in self.events:
                if pred(room_id, ev):
                    return ev
            await self.sync(250)
        raise AssertionError("timed out; last events: " + "; ".join(
            f"{type(e).__name__} {getattr(e, 'sender', '')}" for _, e in self.events[-6:]))

    async def say(self, room_id, body, **extra):
        r = await self.c.room_send(room_id, "m.room.message",
                                   {"msgtype": "m.text", "body": body, **extra},
                                   ignore_unverified_devices=True)
        assert isinstance(r, nio.RoomSendResponse), r
        return r.event_id


def content(ev):
    return (getattr(ev, "source", None) or {}).get("content") or {}


class FakeGitHub:
    def __init__(self):
        self.calls = []

    async def create_issue(self, repo, title, body, labels):
        self.calls.append((repo, title, body, labels))
        return CreatedIssue(7, f"https://github.com/{repo}/issues/7", repo, title)


async def test_issue_in_encrypted_room(tmp_path):
    tag = secrets.token_hex(3)
    bot_id = register(f"issuebot{tag}", "botpass")
    alice_id = register(f"alice{tag}", "alicepass")
    server = bot_id.partition(":")[2]
    cfg = Config(homeserver=HS, user=bot_id, password="botpass", github_token="t",
                 repos={"diddy": "Lndr/diddy"}, labels=["matrix"], data_dir=str(tmp_path),
                 invite_servers=[server])
    gh = FakeGitHub()
    app = IssueBot(cfg, gh, Store(str(tmp_path / "db.sqlite3")))
    runner = asyncio.ensure_future(app.bot.start())
    alice = User(alice_id, "alicepass", str(tmp_path / "alice"))
    try:
        await alice.login()
        room = await alice.c.room_create(
            invite=[bot_id], name="Issue test",
            initial_state=[{"type": "m.room.encryption", "state_key": "",
                            "content": {"algorithm": "m.megolm.v1.aes-sha2"}}],
            power_level_override={"users": {alice_id: 100, bot_id: 50}})
        rid = room.room_id
        await alice.wait_for(lambda r, e: r == rid and isinstance(e, nio.RoomMemberEvent)
                             and e.state_key == bot_id and e.membership == "join")
        for _ in range(40):
            st = await alice.c.room_get_state_event(rid, "dev.diddy.commands", bot_id)
            if isinstance(st, nio.RoomGetStateEventResponse):
                break
            await asyncio.sleep(0.25)
        assert {"issue", "bug", "idee"} <= {c["name"] for c in st.content["commands"]}
        await asyncio.sleep(1)
        await alice.sync()
        await alice.say(rid, "!bug Absturz beim Start | passiert immer")
        reply = await alice.wait_for(lambda r, e: r == rid and e.sender == bot_id
                                     and "dev.diddy.card" in content(e))
        card = content(reply)["dev.diddy.card"]
        assert card["text"] == "#7 angelegt: Absturz beim Start" and card["tone"] == "success"
        assert gh.calls[0][3] == ["matrix", "bug"]
    finally:
        app.bot.stop()
        await asyncio.wait_for(runner, 40)
        await alice.c.close()
