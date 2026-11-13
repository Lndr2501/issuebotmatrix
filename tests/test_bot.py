import time

import pytest

from issuebot import cards
from issuebot.bot import Bot, _md_escape
from issuebot.config import Config
from issuebot.github import CreatedIssue, GitHubError
from issuebot.store import Store

CFG = dict(homeserver="https://m", user="@issuebot:example.org", password="pw", github_token="t",
           repos={"diddy": "Lndr/diddy", "musik": "Lndr/musik"}, labels=["matrix"])


class FakeMatrix:
    def __init__(self):
        self.sent = []

    async def send(self, room_id, content):
        self.sent.append((room_id, content))
        return "$reply"

    def display_name(self, room_id, user_id):
        return "Lndr [x](http://evil)"


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
    def _make(fail=None, **over):
        cfg = Config(**{**CFG, **over})
        m, g = FakeMatrix(), FakeGitHub(fail)
        bot = Bot(cfg, m, g, Store(str(tmp_path / "db.sqlite3")))
        return bot, m, g
    return _make


def now_ms():
    return int(time.time() * 1000)


async def test_creates_issue_and_replies_with_card(make):
    bot, m, g = make()
    await bot.on_text("!r", "@a:example.org", "$e1", "!bug App stürzt ab | beim Öffnen", now_ms())
    repo, title, body, labels = g.calls[0]
    assert (repo, title, labels) == ("Lndr/diddy", "App stürzt ab", ["matrix", "bug"])
    assert body.startswith("beim Öffnen")
    assert "`@a:example.org`" in body and "](http" not in body     # Name entschaerft
    room, content = m.sent[0]
    card = content[cards.CARD_KEY]
    assert card["kind"] == "note" and card["tone"] == "success"
    assert card["url"] == "https://github.com/Lndr/diddy/issues/1"
    assert card["linkLabel"] == "Issue öffnen"
    assert "https://github.com/Lndr/diddy/issues/1" in content["body"]
    assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$e1"


async def test_repo_prefix_and_idea_label(make):
    bot, m, g = make()
    await bot.on_text("!r", "@a:example.org", "$e1", "!idee musik: Lautstärke merken", now_ms())
    assert g.calls[0][0] == "Lndr/musik" and g.calls[0][3] == ["matrix", "enhancement"]


async def test_same_event_only_once(make):
    bot, m, g = make()
    for _ in range(3):
        await bot.on_text("!r", "@a:x", "$same", "!issue Titel", now_ms())
    assert len(g.calls) == 1


async def test_old_messages_are_ignored(make):
    bot, m, g = make()
    await bot.on_text("!r", "@a:x", "$old", "!issue Titel", now_ms() - 3_600_000)
    assert g.calls == [] and m.sent == []


async def test_other_messages_are_ignored(make):
    bot, m, g = make()
    await bot.on_text("!r", "@a:x", "$e", "!play irgendwas", now_ms())
    await bot.on_text("!r", "@a:x", "$f", "hallo", now_ms())
    assert g.calls == [] and m.sent == []


async def test_help(make):
    bot, m, g = make()
    await bot.on_text("!r", "@a:x", "$e", "!issue", now_ms())
    assert g.calls == [] and m.sent[0][1][cards.CARD_KEY]["kind"] == "help"


async def test_rate_limit(make):
    bot, m, g = make(rate_count=2, rate_seconds=600)
    for i in range(3):
        await bot.on_text("!r", "@a:x", f"$e{i}", f"!issue Titel {i}", now_ms())
    assert len(g.calls) == 2
    assert m.sent[-1][1][cards.CARD_KEY]["tone"] == "warning"
    await bot.on_text("!r", "@b:x", "$other", "!issue Anderer Nutzer", now_ms())
    assert len(g.calls) == 3


async def test_allowed_users(make):
    bot, m, g = make(allowed_users=["@lndr:x"])
    await bot.on_text("!r", "@fremd:x", "$e", "!issue Spam", now_ms())
    assert g.calls == [] and m.sent[0][1][cards.CARD_KEY]["tone"] == "error"


async def test_github_error_is_shown(make):
    bot, m, g = make(fail="GitHub-Token ist ungültig oder abgelaufen.")
    await bot.on_text("!r", "@a:x", "$e", "!issue Titel", now_ms())
    content = m.sent[0][1]
    assert content[cards.CARD_KEY]["tone"] == "error"
    assert "Token" in content["body"]


async def test_reporter_off(make):
    bot, m, g = make(reporter="off")
    await bot.on_text("!r", "@a:x", "$e", "!issue Titel", now_ms())
    assert "@a:x" not in g.calls[0][2]


def test_md_escape():
    assert _md_escape("[a](b) @c <img>") == "\\[a\\]\\(b\\) \\@c \\<img\\>"
