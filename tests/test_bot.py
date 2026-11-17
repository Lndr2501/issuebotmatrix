import asyncio

import pytest
from diddybot.testing import TestClient

from issuebot.bot import IssueBot, _md_escape, invite_filter
from issuebot.config import Config
from issuebot.github import CreatedIssue, GitHubError
from issuebot.store import Store

CFG = dict(homeserver="https://m", user="@issuebot:example.org", password="pw", github_token="t",
           repos={"diddy": "Lndr/diddy", "musik": "Lndr/musik"}, labels=["matrix"])


class FakeGitHub:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    async def create_issue(self, repo, title, body, labels):
        self.calls.append((repo, title, body, labels))
        if self.fail:
            raise GitHubError(self.fail)
        n = len(self.calls)
        return CreatedIssue(n, f"https://github.com/{repo}/issues/{n}", repo, title)


@pytest.fixture
def make(tmp_path):
    def _make(fail=None, researcher=None, **over):
        cfg = Config(**{**CFG, "data_dir": str(tmp_path), **over})
        g = FakeGitHub(fail)
        app = IssueBot(cfg, g, Store(str(tmp_path / "db.sqlite3")), researcher)
        chat = TestClient(app.bot, user="@a:example.org")
        return app, chat, g
    return _make


async def test_creates_issue_and_replies_with_card(make):
    app, chat, g = make()
    [m] = await chat.say("!bug App stürzt ab | beim Öffnen")
    repo, title, body, labels = g.calls[0]
    assert (repo, title, labels) == ("Lndr/diddy", "App stürzt ab", ["matrix", "bug"])
    assert body.startswith("beim Öffnen")
    assert "`@a:example.org`" in body
    card = m.card
    assert card["kind"] == "note" and card["tone"] == "success"
    assert card["url"] == "https://github.com/Lndr/diddy/issues/1"
    assert card["linkLabel"] == "Issue öffnen"
    assert card["text"] == "#1 angelegt: App stürzt ab"
    assert "https://github.com/Lndr/diddy/issues/1" in m.body
    assert m.content["m.relates_to"]["m.in_reply_to"]["event_id"] == chat.last_event_id


async def test_multiline_and_aliases(make):
    app, chat, g = make()
    await chat.say("!fehler Titel in Zeile 1\nBeschreibung darunter")
    assert g.calls[0][1] == "Titel in Zeile 1" and g.calls[0][2].startswith("Beschreibung darunter")
    assert g.calls[0][3] == ["matrix", "bug"]


async def test_repo_prefix_and_idea_label(make):
    app, chat, g = make()
    [m] = await chat.say("!idee musik: Lautstärke merken")
    assert g.calls[0][0] == "Lndr/musik" and g.calls[0][3] == ["matrix", "enhancement"]
    assert m.card["text"] == "#1 angelegt in musik: Lautstärke merken"


async def test_other_messages_are_ignored(make):
    app, chat, g = make()
    assert await chat.say("!play irgendwas") == []
    assert await chat.say("hallo") == []
    assert g.calls == []


async def test_help(make):
    app, chat, g = make()
    for text in ("!issue", "!issue hilfe", "!issuebot"):
        [m] = await chat.say(text)
        assert m.card["kind"] == "help", text
    assert g.calls == []


async def test_generic_help_is_left_to_other_bots(make):
    """`!hilfe` / `!help` belong to the other bots in a shared room: the issue bot stays quiet."""
    app, chat, g = make()
    for text in ("!hilfe", "!help"):
        assert await chat.say(text) == [], text


async def test_rate_limit(make):
    app, chat, g = make(rate_count=2, rate_seconds=600)
    for i in range(3):
        out = await chat.say(f"!issue Titel {i}")
    assert len(g.calls) == 2
    assert out[0].card["tone"] == "warning"
    await chat.say("!issue Anderer Nutzer", user="@b:example.org")
    assert len(g.calls) == 3


async def test_allowed_users(make):
    app, chat, g = make(allowed_users=["@lndr:x"])
    [m] = await chat.say("!issue Spam", user="@fremd:x")
    assert g.calls == [] and m.card["tone"] == "error"
    await chat.say("!issue Echt", user="@lndr:x")
    assert len(g.calls) == 1


async def test_github_error_is_shown(make):
    app, chat, g = make(fail="GitHub-Token ist ungültig oder abgelaufen.")
    [m] = await chat.say("!issue Titel")
    assert m.card["tone"] == "error" and "Token" in m.body


async def test_title_missing(make):
    app, chat, g = make()
    [m] = await chat.say("!issue |")
    assert g.calls == [] and m.card["tone"] == "error"


async def test_reporter_off_and_name_is_escaped(make):
    app, chat, g = make(reporter="off")
    await chat.say("!issue Titel")
    assert "@a:example.org" not in g.calls[0][2]
    app, chat, g = make(reporter="name")
    await chat.arrive("@a:example.org", name="Lndr [x](http://evil)")
    await chat.say("!issue Titel")
    assert "](http" not in g.calls[0][2] and "`@a:example.org`" in g.calls[0][2]


def test_md_escape():
    assert _md_escape("[a](b) @c <img>") == "\\[a\\]\\(b\\) \\@c \\<img\\>"


def test_invite_filter():
    cfg = Config(**CFG)
    allowed = invite_filter(cfg)
    assert allowed("@x:example.org", "!r") and not allowed("@x:evil.org", "!r") and not allowed("", "!r")
    cfg.allowed_users = ["@lndr:other.org"]
    assert allowed("@lndr:other.org", "!r") and not allowed("@x:example.org", "!r")
    cfg.allowed_users, cfg.invite_servers = [], ["a.org", "b.org"]
    assert allowed("@x:b.org", "!r") and not allowed("@x:example.org", "!r")


async def test_commands_for_diddy(make):
    app, chat, g = make()
    await chat.start()
    names = [c["name"] for c in chat.commands()["commands"]]
    assert {"issue", "bug", "idee", "issuebot"} <= set(names) and "hilfe" not in names and "help" not in names
    assert chat.profile()["about"].startswith("Legt GitHub-Issues an")


class FakeResearcher:
    def __init__(self):
        self.calls = []

    async def run(self, repo, number):
        self.calls.append((repo, number))


async def test_research_starts_in_background(make):
    r = FakeResearcher()
    app, chat, g = make(researcher=r)
    assert await chat.say("!issue Titel")          # Antwort kommt sofort
    await asyncio.gather(*app._tasks)
    assert r.calls == [("Lndr/diddy", 1)]
