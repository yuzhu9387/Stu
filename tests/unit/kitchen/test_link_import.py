"""A recipe from a pasted link: the server reads only public pages, checks
every hop of a redirect, stops at ten seconds and two megabytes, and keeps
the page's words (title, description, recipe data, visible text), never its
scripts. What it cannot read, it says so."""

import json

import httpx
import pytest

from recipe_agent.domain.kitchen import ai as kitchen_ai
from recipe_agent.domain.kitchen.ai import ImportLinkRequest, KitchenAI
from recipe_agent.domain.kitchen.link_import import (
    MAX_BYTES,
    UNREADABLE,
    LinkError,
    fetch_page_text,
    page_text,
)
from tests.unit.kitchen.test_ai_scheduling_mcp import MemoryRepository
from tests.unit.kitchen.test_ai_variety import SequenceProvider

from .test_dish_baskets import household

PUBLIC = {"recipes.example": ["93.184.216.34"], "cdn.example": ["2606:4700::6810:84e5"]}
PAGE = """<!doctype html><html><head>
<title>番茄炒蛋 | Home Kitchen</title>
<meta name="description" content="Soft eggs with tomato, ready in 10 minutes.">
<meta property="og:title" content="番茄炒蛋">
<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "ignored"},
  {"@type": "Recipe", "name": "番茄炒蛋", "recipeYield": "2 servings", "totalTime": "PT10M",
   "recipeIngredient": ["鸡蛋 3个", "番茄 2个"],
   "recipeInstructions": [{"@type": "HowToStep", "text": "番茄切块"}, "鸡蛋打散炒熟"]}]}</script>
<style>.hidden{display:none}</style>
<script>window.secret = "do not read me";</script>
</head><body><nav>Menu</nav><article><h1>番茄炒蛋</h1><p>先炒蛋 再炒番茄。</p></article>
<noscript>Enable JavaScript</noscript></body></html>"""


async def resolver(host, port):
    if host in PUBLIC:
        return PUBLIC[host]
    if host == "localhost":
        return ["127.0.0.1"]
    if host == "sneaky.example":
        return ["93.184.216.34", "10.1.2.3"]
    raise OSError("no such host")


def site(routes):
    """A transport serving `routes` by the Host the request was sent for."""
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["host"], request.url.host, request.url.path))
        return routes[request.headers["host"] + request.url.path]()

    return httpx.MockTransport(handle), seen


def html(body=PAGE, **headers):
    return lambda: httpx.Response(
        200, headers={"content-type": "text/html; charset=utf-8", **headers}, content=body
    )


async def read(url, routes):
    transport, seen = site(routes)
    text = await fetch_page_text(url, transport=transport, resolver=resolver)
    return text, seen


async def test_a_public_page_is_read_as_words_only():
    text, seen = await read("https://recipes.example/eggs", {"recipes.example/eggs": html()})
    assert "番茄炒蛋 | Home Kitchen" in text
    assert "Soft eggs with tomato, ready in 10 minutes." in text
    assert "鸡蛋 3个" in text and "番茄切块" in text and "鸡蛋打散炒熟" in text
    assert "先炒蛋 再炒番茄。" in text
    assert "do not read me" not in text and "display:none" not in text
    assert "Enable JavaScript" not in text
    # The request went to the address that was checked, named for its host.
    assert seen == [("recipes.example", "93.184.216.34", "/eggs")]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://10.0.0.1/",
        "http://127.0.0.1:8000/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://sneaky.example/",
        "ftp://recipes.example/eggs",
        "file:///etc/passwd",
        "https://user:pass@recipes.example/eggs",
        "https://nowhere.example/",
    ],
)
async def test_only_public_http_pages_are_fetched(url):
    transport, seen = site({})
    with pytest.raises(LinkError):
        await fetch_page_text(url, transport=transport, resolver=resolver)
    assert seen == []


async def test_a_redirect_to_a_private_address_is_refused_before_it_is_followed():
    def moved():
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(LinkError):
        await read("https://recipes.example/go", {"recipes.example/go": moved})


async def test_redirects_are_followed_a_few_times_only():
    hop = {
        f"recipes.example/{n}": (lambda n=n: httpx.Response(301, headers={"location": f"/{n + 1}"}))
        for n in range(5)
    }
    with pytest.raises(LinkError, match="redirect"):
        await read("https://recipes.example/0", hop)
    text, seen = await read(
        "https://recipes.example/0",
        {**{k: v for k, v in hop.items() if k < "recipes.example/3"}, "recipes.example/3": html()},
    )
    assert "番茄炒蛋" in text and len(seen) == 4


async def test_a_page_too_large_is_refused():
    big = html(b"<p>" + b"x" * (MAX_BYTES + 1) + b"</p>")
    with pytest.raises(LinkError, match="too large"):
        await read("https://recipes.example/big", {"recipes.example/big": big})
    declared = html("<p>ok</p>", **{"content-length": str(MAX_BYTES + 1)})
    with pytest.raises(LinkError, match="too large"):
        await read("https://recipes.example/big", {"recipes.example/big": declared})


async def test_a_page_with_nothing_to_read_says_to_paste_instead():
    empty = html("<html><head><title></title></head><body><script>app()</script></body></html>")
    with pytest.raises(LinkError) as caught:
        await read("https://recipes.example/app", {"recipes.example/app": empty})
    assert str(caught.value) == UNREADABLE
    assert "Paste the text or a screenshot instead" in UNREADABLE
    image = lambda: httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")  # noqa: E731
    with pytest.raises(LinkError):
        await read("https://recipes.example/pic", {"recipes.example/pic": image})
    missing = lambda: httpx.Response(404, text="gone")  # noqa: E731
    with pytest.raises(LinkError):
        await read("https://recipes.example/gone", {"recipes.example/gone": missing})


def test_page_text_is_capped():
    assert len(page_text("<p>" + "长" * 50_000 + "</p>")) <= 20_000


async def test_import_link_hands_the_words_to_extract_and_keeps_the_link(monkeypatch):
    async def fetched(url):
        assert url == "https://recipes.example/eggs"
        return "Title: 番茄炒蛋\nIngredients: 鸡蛋 3个"

    monkeypatch.setattr(kitchen_ai, "fetch_page_text", fetched)
    candidate = {
        "id": "draft",
        "liked": False,
        "source": "page",
        "name": "番茄炒蛋",
        "type": "Protein",
        "mealTypes": ["dinner"],
        "tags": [],
        "servings": 2,
        "activeMinutes": 10,
        "elapsedMinutes": 10,
        "ingredients": [{"name": "鸡蛋", "quantity": 3, "unit": "个"}],
        "steps": ["炒"],
        "incomplete": True,
    }
    provider = SequenceProvider({"recipes": [candidate]})
    repository = MemoryRepository(household())
    before = json.dumps(repository.state, sort_keys=True)
    result = await KitchenAI(repository, None, provider).import_link(
        "household", ImportLinkRequest(url="https://recipes.example/eggs")
    )
    assert result["recipes"][0]["source"] == "https://recipes.example/eggs"
    assert "鸡蛋 3个" in provider.requests[0][1]["content"][0]["text"]
    assert json.dumps(repository.state, sort_keys=True) == before


async def test_an_ipv6_host_is_asked_at_its_checked_address():
    text, seen = await read("https://cdn.example/eggs", {"cdn.example/eggs": html()})
    assert "番茄炒蛋" in text
    assert seen == [("cdn.example", "2606:4700::6810:84e5", "/eggs")]


async def test_a_page_without_a_closing_head_is_still_read():
    page = html("<html><head><title>Soup</title><body><p>Simmer the broth for an hour.</p>")
    text, _ = await read("https://recipes.example/soup", {"recipes.example/soup": page})
    assert "Simmer the broth for an hour." in text


async def test_a_slow_page_is_given_up_on(monkeypatch):
    import asyncio

    from recipe_agent.domain.kitchen import link_import

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, text="late")

    monkeypatch.setattr(link_import, "TIMEOUT_SECONDS", 0.05)
    with pytest.raises(LinkError) as caught:
        await fetch_page_text(
            "https://recipes.example/slow", transport=httpx.MockTransport(slow), resolver=resolver
        )
    assert str(caught.value) == UNREADABLE


def test_a_youtube_page_gives_its_whole_description():
    full = "番茄炒蛋做法: 鸡蛋3个 番茄2个 盐少许。1. 番茄切块 2. 鸡蛋炒熟盛出 3. 番茄炒软后回锅"
    player = json.dumps(
        {"videoDetails": {"title": "番茄炒蛋", "shortDescription": full}}, ensure_ascii=False
    )
    page = f"""<html><head><title>番茄炒蛋 - YouTube</title>
    <meta name="description" content="番茄炒蛋做法: 鸡蛋3个 番茄2个…">
    <script>var ytInitialPlayerResponse = {player};var meta = 1;</script>
    </head><body><p>About Press Copyright</p></body></html>"""
    text = page_text(page)
    assert full in text


def test_a_bilibili_page_gives_its_video_description():
    state = {
        "videoData": {
            "title": "十分钟快手菜",
            "desc": "准备: 土豆1个 青椒1个。先炒土豆丝再下青椒。",
        }
    }
    page = f"""<html><head><title>十分钟快手菜_哔哩哔哩_bilibili</title></head><body>
    <script>window.__INITIAL_STATE__={json.dumps(state, ensure_ascii=False)};(function(){{}})()
    </script>
    </body></html>"""
    text = page_text(page)
    assert "先炒土豆丝再下青椒" in text and "十分钟快手菜" in text


def test_page_data_that_is_not_json_is_ignored():
    page = (
        "<html><head><title>x</title><script>var ytInitialPlayerResponse = {broken;</script>"
        "</head><body><p>A long enough page body to read.</p></body></html>"
    )
    assert "A long enough page body to read." in page_text(page)


async def test_a_page_without_a_recipe_says_to_paste_instead(monkeypatch):
    async def fetched(url):
        return "Title: About us\nPage text: We are a small company making kitchen tools."

    monkeypatch.setattr(kitchen_ai, "fetch_page_text", fetched)
    provider = SequenceProvider({"recipes": []})
    with pytest.raises(LinkError) as caught:
        await KitchenAI(MemoryRepository(household()), None, provider).import_link(
            "household", ImportLinkRequest(url="https://recipes.example/about")
        )
    assert "Paste the text or a screenshot instead" in str(caught.value)
