import pytest
from aiohttp import web

from issuebot.research import AIError, ChatAI


@pytest.fixture
async def llm(aiohttp_server):
    seen = []

    async def chat(request):
        body = await request.json()
        seen.append((request.headers.get("Authorization"), body))
        if "response_format" in body and request.app["no_json_mode"]:
            return web.json_response({"error": "unknown field response_format"}, status=400)
        return web.json_response({"choices": [{"message": {"content": '<think>..</think>{"ok": true}'}}]})

    app = web.Application()
    app["no_json_mode"] = False
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    return str(server.make_url("/v1")), app, seen


async def test_chat_json_with_key(llm):
    url, _, seen = llm
    assert await ChatAI(url, "m", "sk-test").chat_json("s", "u") == {"ok": True}
    assert seen[0][0] == "Bearer sk-test" and seen[0][1]["model"] == "m"


async def test_falls_back_without_json_mode(llm):
    url, app, seen = llm
    app["no_json_mode"] = True
    ai = ChatAI(url, "m")
    assert await ai.chat_json("s", "u") == {"ok": True}
    assert "response_format" not in seen[-1][1]
    await ai.chat_json("s", "u")                 # merkt sich das
    assert "response_format" not in seen[-1][1] and seen[-1][0] is None


async def test_unreachable():
    with pytest.raises(AIError):
        await ChatAI("http://127.0.0.1:9/v1", "m", timeout=2).chat_json("s", "u")
