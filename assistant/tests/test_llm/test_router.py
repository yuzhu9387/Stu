import pytest
from app.llm.config import resolve_model
from app.llm.router import LLMError, LLMRouter


def test_resolve_model_default_think():
    assert "haiku" in resolve_model("think").lower()


def test_resolve_model_default_react():
    assert "sonnet" in resolve_model("react").lower()


def test_resolve_model_invalid_raises():
    with pytest.raises(KeyError):
        resolve_model("bogus")  # type: ignore[arg-type]


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


async def test_complete_returns_text(monkeypatch):
    async def fake_acompletion(**kwargs):
        assert kwargs["model"]  # was resolved
        return _FakeResponse("hello")
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert out == "hello"


async def test_complete_json_parses(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('{"intent": "test", "actions": []}')
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete_json("think", [{"role": "user", "content": "hi"}])
    assert out["intent"] == "test"


async def test_complete_json_strips_codefences(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('```json\n{"ok": true}\n```')
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete_json("think", [{"role": "user", "content": "hi"}])
    assert out["ok"] is True


async def test_resolve_model_reasoning():
    assert "opus" in resolve_model("reasoning").lower()


async def test_complete_wraps_litellm_exception(monkeypatch):
    async def fake_acompletion(**kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    with pytest.raises(LLMError):
        await router.complete("react", [{"role": "user", "content": "hi"}])


async def test_complete_json_raises_on_bad_json(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse("not json at all")
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    with pytest.raises(LLMError):
        await router.complete_json("think", [{"role": "user", "content": "hi"}])


async def test_complete_raises_on_none_content(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse(None)
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    with pytest.raises(LLMError):
        await router.complete("react", [{"role": "user", "content": "hi"}])


from types import SimpleNamespace


async def test_complete_passes_tools_kwarg(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse("ok")

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    await router.complete(
        "react",
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )
    assert captured.get("tools") == [{"type": "web_search_20250305", "name": "web_search"}]


async def test_complete_does_not_pass_tools_when_none(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse("ok")

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "tools" not in captured


async def test_complete_extracts_text_from_list_content(monkeypatch):
    """When tools are used, message.content may be a list of blocks."""
    content_blocks = [
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "tool_result", "tool_use_id": "x", "content": "search results"},
        {"type": "text", "text": "Based on my search, here's the answer."},
    ]
    fake_msg = SimpleNamespace(content=content_blocks)
    fake_choice = SimpleNamespace(message=fake_msg)
    fake_resp = SimpleNamespace(choices=[fake_choice])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    result = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "Based on my search" in result
    assert "tool_use" not in result.lower()


async def test_complete_handles_multiple_text_blocks(monkeypatch):
    """Sometimes Claude emits multiple text blocks across a tool sequence."""
    content_blocks = [
        {"type": "text", "text": "Let me search first."},
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "tool_result", "tool_use_id": "x", "content": "results"},
        {"type": "text", "text": "Based on what I found, here's my reply."},
    ]
    fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content_blocks))])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    result = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "Let me search first" in result
    assert "Based on what I found" in result


async def test_complete_raises_when_only_tool_blocks(monkeypatch):
    """If response is all tool blocks with no text, we have nothing to return."""
    content_blocks = [
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
    ]
    fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content_blocks))])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    with pytest.raises(LLMError):
        await router.complete("react", [{"role": "user", "content": "hi"}])
