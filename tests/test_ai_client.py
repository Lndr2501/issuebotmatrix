import json

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


@pytest.fixture
async def sse_llm(aiohttp_server):
    seen = []

    async def chat(request):
        body = await request.json()
        seen.append(body)
        if "reasoning_effort" in body and request.app["no_effort"]:
            return web.json_response({"error": "unknown reasoning_effort"}, status=400)
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        chunks = [{"choices": [{"delta": {"reasoning_content": "denke {nach}"}}]},
                  {"choices": [{"delta": {"content": '{"terms": '}}]},
                  {"choices": [{"delta": {"content": '["BotCard"]}'}, "finish_reason": "stop"}]}]
        for c in chunks:
            await resp.write(f"data: {json.dumps(c)}\n\n".encode())
        await resp.write(b"data: [DONE]\n\n")
        return resp

    app = web.Application()
    app["no_effort"] = False
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    return str(server.make_url("/v1")), app, seen


async def test_streamed_answer_without_reasoning_text(sse_llm):
    url, _, seen = sse_llm
    ai = ChatAI(url, "m", reasoning="medium")
    assert await ai.chat_json("s", "u", reasoning="low") == {"terms": ["BotCard"]}
    assert seen[0]["stream"] is True and seen[0]["reasoning_effort"] == "low"
    await ai.chat_json("s", "u")
    assert seen[-1]["reasoning_effort"] == "medium"


async def test_reasoning_dropped_when_rejected(sse_llm):
    url, app, seen = sse_llm
    app["no_effort"] = True
    ai = ChatAI(url, "m", reasoning="high")
    assert await ai.chat_json("s", "u") == {"terms": ["BotCard"]}
    assert "reasoning_effort" not in seen[-1] and ai.reasoning == ""


async def test_no_reasoning_field_when_not_configured(sse_llm):
    url, _, seen = sse_llm
    await ChatAI(url, "m").chat_json("s", "u", reasoning="low")
    assert "reasoning_effort" not in seen[-1]


async def test_second_try_without_json_mode_after_broken_json(aiohttp_server):
    seen = []

    async def chat(request):
        body = await request.json()
        seen.append(body)
        if "response_format" in body:
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            err = {"error": {"code": "structured_output_failed", "message": "model did not return valid JSON"}}
            await resp.write(f"data: {json.dumps(err)}\n\n".encode())
            return resp
        return web.json_response({"choices": [{"message": {"content": 'Hier: {"ok": 1}'}}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    ai = ChatAI(str(server.make_url("/v1")), "m")
    assert await ai.chat_json("s", "u") == {"ok": 1}
    assert "response_format" in seen[0] and "response_format" not in seen[1]
    assert ai._json_mode is True          # naechstes Mal wieder mit JSON-Modus


async def test_reasoning_none_stays_off_for_search(sse_llm):
    url, _, seen = sse_llm
    await ChatAI(url, "m", reasoning="none").chat_json("s", "u", reasoning="low")
    assert seen[0]["reasoning_effort"] == "none"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors_are_not_retried_or_echoed(aiohttp_server, status):
    seen = []

    async def chat(request):
        seen.append(await request.json())
        return web.json_response({"error": "secret-reflected-by-proxy"}, status=status)

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    with pytest.raises(AIError, match=f"HTTP {status}") as exc:
        await ChatAI(str(server.make_url("/v1")), "m").chat_json("s", "u")
    assert "secret-reflected" not in str(exc.value) and len(seen) == 1


async def test_http_structured_output_failure_retries_without_json(aiohttp_server):
    seen = []

    async def chat(request):
        body = await request.json()
        seen.append(body)
        if "response_format" in body:
            return web.json_response({"error": {"code": "structured_output_failed"}}, status=422)
        return web.json_response({"choices": [{"message": {"content": '{"ok": true}'}}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    assert await ChatAI(str(server.make_url("/v1")), "m").chat_json("s", "u") == {"ok": True}
    assert len(seen) == 2 and "response_format" not in seen[-1]


@pytest.mark.parametrize("mode", ["length", "eof", "malformed", "wrong-content"])
async def test_bad_stream_never_returns_partial_result(aiohttp_server, mode):
    seen = []

    async def chat(request):
        seen.append(await request.json())
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        content = 17 if mode == "wrong-content" else '{"ok": true}'
        chunk = {"choices": [{"delta": {"content": content}}]}
        if mode == "length":
            chunk["choices"][0]["finish_reason"] = "length"
        await resp.write(f"data: {json.dumps(chunk)}\n\n".encode())
        if mode == "malformed":
            await resp.write(b"data: {broken\n\n")
        if mode != "eof":
            await resp.write(b"data: [DONE]\n\n")
        return resp

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    server = await aiohttp_server(app)
    with pytest.raises(AIError):
        await ChatAI(str(server.make_url("/v1")), "m").chat_json("s", "u")
    assert len(seen) == 3  # zwei Wiederholungsversuche, keine Endlosschleife
