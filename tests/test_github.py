import pytest
from aiohttp import web

from issuebot.github import GitHub, GitHubError


@pytest.fixture
async def api(aiohttp_server):
    seen = {}

    async def create(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.path
        data = await request.json()
        seen["data"] = data
        if data["title"] == "kaputt":
            return web.json_response({"message": "Bad credentials"}, status=401)
        if data["title"] == "verboten":
            return web.json_response({"message": "Resource not accessible"}, status=403)
        return web.json_response({"number": 7, "html_url": "https://github.com/o/r/issues/7",
                                  "title": data["title"]}, status=201)

    app = web.Application()
    app.router.add_post("/repos/{owner}/{repo}/issues", create)
    server = await aiohttp_server(app)
    return str(server.make_url("")), seen


async def test_create(api):
    url, seen = api
    issue = await GitHub("geheim", api=url).create_issue("o/r", "Titel", "Text", ["matrix"])
    assert (issue.number, issue.url) == (7, "https://github.com/o/r/issues/7")
    assert seen["auth"] == "Bearer geheim" and seen["path"] == "/repos/o/r/issues"
    assert seen["data"] == {"title": "Titel", "body": "Text", "labels": ["matrix"]}


@pytest.mark.parametrize("title,needle", [("kaputt", "Token"), ("verboten", "Kein Zugriff")])
async def test_errors_are_readable_and_hide_token(api, title, needle):
    url, _ = api
    with pytest.raises(GitHubError) as exc:
        await GitHub("geheim", api=url).create_issue("o/r", title, "", [])
    assert needle in str(exc.value) and "geheim" not in str(exc.value)


async def test_unreachable():
    with pytest.raises(GitHubError):
        await GitHub("t", api="http://127.0.0.1:9", timeout=2).create_issue("o/r", "x", "", [])
