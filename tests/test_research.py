import io
import json
import tarfile

import pytest

from issuebot.codesearch import CodeIndex
from issuebot.research import (MARKER, AIError, Researcher, check_analysis, parse_json_reply,
                               render_body)

PLAYER = "\n".join(
    ["import x"] * 9
    + ["function pausePlayback(card) {", "  // pausiert die Karte", "  card.state = 'paused';", "}"]
    + ["// filler"] * 30
)
FILES = {
    "cinny/src/app/BotCard.tsx": PLAYER,
    "cinny/src/app/other.ts": "export const a = 1;\n",
    "README.md": "pausePlayback wird in der Doku erwaehnt\n",
    "node_modules/lib/index.js": "pausePlayback()\n",
    "assets/logo.png": "\x00\x01binary",
}


def make_tar(files=FILES) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"Lndr-diddy-abc123/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_index_skips_vendor_and_binary():
    idx = CodeIndex.from_tarball(make_tar())
    assert set(idx.files) == {"cinny/src/app/BotCard.tsx", "cinny/src/app/other.ts", "README.md"}


def test_search_ranks_code_before_docs_and_snippets_have_line_numbers():
    idx = CodeIndex.from_tarball(make_tar())
    hits = idx.search(["pausePlayback", "paused", "x"])        # "x" ist zu kurz
    assert hits[0].path == "cinny/src/app/BotCard.tsx"
    assert hits[0].lines[:2] == [10, 12]
    text = idx.snippets(hits, 5000)
    assert "   10| function pausePlayback(card) {" in text


def test_valid_range():
    idx = CodeIndex.from_tarball(make_tar())
    assert idx.valid_range("cinny/src/app/BotCard.tsx", 10, 13) == (10, 13)
    assert idx.valid_range("cinny/src/app/BotCard.tsx", 40, 999) == (40, 43)
    assert idx.valid_range("gibts/nicht.ts", 1, 2) is None
    assert idx.valid_range("cinny/src/app/BotCard.tsx", 999, 1000) is None
    assert CodeIndex({"empty.py": []}).valid_range("empty.py", 1, 1) is None


def test_snippet_budget_covers_multiple_platforms_and_limits_windows():
    idx = CodeIndex({f"{platform}/main.ts": ["const preview = '" + "x" * 100 + "';"] * 100
                     for platform in ("desktop", "ios", "android", "web")})
    snippets = idx.snippets(idx.search(["preview"]), 2500)
    assert len(snippets) <= 2500
    for platform in ("desktop", "ios", "android", "web"):
        assert f"### {platform}/main.ts " in snippets
    assert idx.snippets(idx.search(["preview"]), 0) == ""
    import re
    assert all(int(b) - int(a) < 40 for a, b in re.findall(r"Zeilen (\d+)-(\d+)", snippets))


def test_search_penalizes_tools_compared_with_runtime_code():
    idx = CodeIndex({"ios/Tools/check/main.swift": ["preview"], "ios/Diddy/UI/Preview.swift": ["preview"]})
    assert idx.search(["preview"])[0].path == "ios/Diddy/UI/Preview.swift"


def test_parse_json_reply_tolerates_think_and_fences():
    assert parse_json_reply('<think>hmm {"x":0}</think>Hier:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('Klar! {"terms": ["a"]} Viel Erfolg') == {"terms": ["a"]}
    with pytest.raises(AIError):
        parse_json_reply("leider nein")


def test_check_analysis_drops_invented_code():
    idx = CodeIndex.from_tarball(make_tar())
    a = check_analysis({
        "title": "  Karte bleibt nach Pause stehen ", "summary": "Problem",
        "code": [{"path": "./cinny/src/app/BotCard.tsx", "start": 10, "end": 13, "why": "hier"},
                 {"path": "erfunden.ts", "start": 1, "end": 5},
                 {"path": "cinny/src/app/BotCard.tsx", "start": "x"}],
        "steps": "kein array",
    }, idx)
    assert a.title == "Karte bleibt nach Pause stehen"
    assert a.code == [{"path": "cinny/src/app/BotCard.tsx", "start": 10, "end": 13, "why": "hier"}]
    assert a.steps == []


def test_render_body_permalinks_and_no_mentions():
    idx = CodeIndex.from_tarball(make_tar())
    a = check_analysis({"summary": "Frag @someone dazu", "hints": ["@team pingen"],
                        "code": [{"path": "cinny/src/app/BotCard.tsx", "start": 10, "end": 13}]}, idx)
    body = render_body(a, "Lndr/diddy", "abc1234def", "Alt", "alter Text", "qwen")
    assert body.startswith(MARKER)
    assert "\nhttps://github.com/Lndr/diddy/blob/abc1234def/cinny/src/app/BotCard.tsx#L10-L13\n" in body
    assert "@someone" not in body and "@​someone" in body
    assert "<summary>Originalmeldung</summary>" in body and "alter Text" in body


class FakeAI:
    model = "test-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def chat_json(self, system, user, reasoning=None):
        self.prompts.append(user)
        return self.replies.pop(0)


class FakeGH:
    def __init__(self, body="Karte pausiert nicht\n\n---\n<sub>Gemeldet über Matrix von x.</sub>"):
        self.issue = {"title": "pause kaputt", "body": body}
        self.updates = []
        self.tarballs = 0

    async def get_issue(self, repo, n):
        return self.issue

    async def head_sha(self, repo):
        return "abc1234def"

    async def repo_info(self, repo):
        return {"description": "Matrix chat client"}

    async def tarball(self, repo, sha):
        self.tarballs += 1
        return make_tar()

    async def update_issue(self, repo, n, title=None, body=None):
        self.updates.append((title, body))


async def test_researcher_full_flow():
    ai = FakeAI([
        {"meaning": "Karte bleibt auf Spielt", "terms": ["pausePlayback", "paused"], "paths": ["cinny/src"]},
        {"type": "bug", "title": "Bot-Karte bleibt nach Pause auf „Spielt“", "summary": "Die Karte wechselt nicht.",
         "code": [{"path": "cinny/src/app/BotCard.tsx", "start": 10, "end": 13, "why": "setzt state"}]},
    ])
    gh = FakeGH()
    a = await Researcher(ai, gh).run("Lndr/diddy", 5)
    assert len(a.code) == 1
    title, body = gh.updates[0]
    assert title == "Bot-Karte bleibt nach Pause auf „Spielt“"
    assert "#L10-L13" in body and "Karte pausiert nicht" in body
    assert "   10| function pausePlayback" in ai.prompts[1]          # Code ging an die KI
    assert "Vorab-Deutung (pruefen!): Karte bleibt auf Spielt" in ai.prompts[1]
    assert "Gemeldet über Matrix" not in ai.prompts[0]              # Fusszeile nicht
    assert "Beschreibung: Matrix chat client" in ai.prompts[0]      # Projekt-Kontext


async def test_researcher_skips_done_issue_and_caches_index():
    gh = FakeGH(body=MARKER + "\nschon fertig")
    r = Researcher(FakeAI([]), gh)
    assert await r.run("Lndr/diddy", 5) is None and gh.updates == []
    await r.index_for("Lndr/diddy")
    await r.index_for("Lndr/diddy")
    assert gh.tarballs == 1


def test_code_must_be_in_shown_snippets_and_not_clamped():
    idx = CodeIndex.from_tarball(make_tar())
    snippets = "### cinny/src/app/BotCard.tsx (Zeilen 10-13)\n"
    a = check_analysis({"summary": "x", "code": [
        {"path": "cinny/src/app/BotCard.tsx", "start": 10, "end": 13},
        {"path": "cinny/src/app/BotCard.tsx", "start": 14, "end": 16},
        {"path": "cinny/src/app/BotCard.tsx", "start": 999, "end": 1000},
        {"path": "cinny/src/app/other.ts", "start": 1, "end": 1},
    ]}, idx, snippets)
    assert len(a.code) == 1 and a.code[0]["start"] == 10
    assert check_analysis({"code": {"wrong": "shape"}}, idx).code == []
    assert check_analysis({"code": [{"path": "cinny/src/app/BotCard.tsx", "start": 1, "end": 43}]}, idx).code == []


async def test_researcher_preserves_concurrent_user_edit():
    gh = FakeGH()

    class EditingAI(FakeAI):
        async def chat_json(self, system, user, reasoning=None):
            reply = await super().chat_json(system, user, reasoning)
            gh.issue = {**gh.issue, "body": "Vom Menschen inzwischen bearbeitet"}
            return reply

    ai = EditingAI([{"terms": []}, {"title": "Neuer Titel", "summary": "x"}])
    assert await Researcher(ai, gh).run("Lndr/diddy", 5) is None
    assert gh.updates == []


def test_feature_kind_is_rendered_and_unknown_kind_is_dropped():
    idx = CodeIndex.from_tarball(make_tar())
    a = check_analysis({"type": "feature", "summary": "Wunsch"}, idx)
    assert "✨ Wunsch" in render_body(a, "Lndr/diddy", "abc", "Alt", "Text", "qwen")
    assert check_analysis({"type": "nonsense"}, idx).kind == ""


async def test_unclear_analysis_keeps_original_title():
    ai = FakeAI([{"terms": []}, {"type": "unklar", "title": "Spekulativer neuer Titel", "summary": "Unklar"}])
    gh = FakeGH()
    await Researcher(ai, gh).run("Lndr/diddy", 5)
    assert gh.updates[0][0] is None


async def test_keep_title_when_disabled():
    ai = FakeAI([{"terms": []}, {"title": "Neuer Titel", "summary": "x"}])
    gh = FakeGH()
    await Researcher(ai, gh, rewrite_title=False).run("Lndr/diddy", 5)
    assert gh.updates[0][0] is None


class CommentedGH(FakeGH):
    """Zwischen den Abrufen kommentiert jemand: updated_at aendert sich, Titel/Text nicht."""

    def __init__(self, edit_body=False):
        super().__init__()
        self.calls = 0
        self.edit_body = edit_body

    async def get_issue(self, repo, n):
        self.calls += 1
        issue = dict(self.issue, updated_at=f"t{self.calls}")
        if self.edit_body and self.calls > 1:
            issue["body"] = "vom Melder ergaenzt"
        return issue


async def test_comment_during_research_does_not_block_update():
    ai = FakeAI([{"terms": []}, {"type": "bug", "title": "Neuer Titel", "summary": "x"}])
    gh = CommentedGH()
    await Researcher(ai, gh).run("Lndr/diddy", 5)
    assert len(gh.updates) == 1


async def test_edited_text_during_research_is_kept():
    ai = FakeAI([{"terms": []}, {"type": "bug", "title": "Neuer Titel", "summary": "x"}])
    gh = CommentedGH(edit_body=True)
    assert await Researcher(ai, gh).run("Lndr/diddy", 5) is None
    assert gh.updates == []
