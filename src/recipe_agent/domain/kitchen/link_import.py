"""Reading a recipe page the household pasted a link to, safely.

The server fetches the page on the household's behalf, so only a public page
is read: http or https, a host whose every address is public (checked again
after each redirect, and the request goes to the very address checked), ten
seconds and two megabytes at most. Only the page's words are kept: its title,
description, recipe data and visible text. Nothing on the page runs.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Awaitable, Callable, Iterator
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10.0
MAX_TEXT = 20_000
UNREADABLE = "This link could not be read. Paste the text or a screenshot instead."
READABLE_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class LinkError(ValueError):
    """A link that was not read, and why, in words for the household."""


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def public(address: str) -> bool:
    """An address anyone on the internet could reach: not this machine, the
    local network, link-local metadata, multicast or anything reserved."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def addresses(host: str, port: int, resolver: Resolver) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        pass
    try:
        found = await resolver(host, port)
    except OSError as exc:
        raise LinkError("That link's website could not be found") from exc
    return found


async def fetch(url: str, *, transport: httpx.AsyncBaseTransport | None, resolver: Resolver) -> str:
    """The page's HTML (or text), following at most a few redirects."""
    current = url
    async with httpx.AsyncClient(
        transport=transport,
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; StuRecipeReader/1.0)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
        },
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise LinkError("Only http and https links can be read")
            if parts.username or parts.password:
                raise LinkError("Links with a user name or password are not read")
            try:
                port = parts.port or (443 if parts.scheme == "https" else 80)
            except ValueError as exc:
                raise LinkError("That link is not a web address") from exc
            found = await addresses(parts.hostname, port, resolver)
            if not found or not all(public(address) for address in found):
                raise LinkError("That link points to a private address, so it is not read")
            # Ask the address just checked, so a second lookup cannot swap it.
            target = httpx.URL(current).copy_with(host=found[0])
            default = port == (443 if parts.scheme == "https" else 80)
            request = client.build_request(
                "GET",
                target,
                headers={"Host": parts.hostname if default else f"{parts.hostname}:{port}"},
                extensions={"sni_hostname": parts.hostname} if parts.scheme == "https" else {},
            )
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise LinkError(UNREADABLE)
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise LinkError(UNREADABLE)
                kind = response.headers.get("content-type", "text/html").split(";")[0].strip()
                if kind.lower() not in READABLE_TYPES:
                    raise LinkError(UNREADABLE)
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BYTES:
                    raise LinkError("That page is too large to read")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise LinkError("That page is too large to read")
                return decode(bytes(body), response.charset_encoding)
            finally:
                await response.aclose()
    raise LinkError("That link redirects too many times")


def decode(body: bytes, charset: str | None) -> str:
    if not charset:
        found = re.search(rb"""charset=["']?([\w-]+)""", body[:4096], re.IGNORECASE)
        charset = found.group(1).decode("ascii") if found else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def fetch_page_text(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = resolve,
) -> str:
    """The words of a public recipe page, or a LinkError saying why not."""
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            page = await fetch(url.strip(), transport=transport, resolver=resolver)
    except TimeoutError as exc:
        raise LinkError(UNREADABLE) from exc
    except httpx.HTTPError as exc:
        raise LinkError(UNREADABLE) from exc
    text = page_text(page)
    if not text:
        raise LinkError(UNREADABLE)
    return text


# ── From HTML to words ───────────────────────────────────────────────────────

SKIPPED = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object"}
BLOCKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}


class Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.meta: dict[str, str] = {}
        self.data: list[str] = []
        self.scripts: list[str] = []
        self.text: list[str] = []
        self.skipping: list[str] = []
        self.in_title = False
        self.in_data = False
        self.in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            if key in {"description", "og:description", "og:title", "twitter:description"}:
                self.meta.setdefault(key, values.get("content", "").strip())
            return
        if tag == "body" and "head" in self.skipping:
            # A page may leave </head> out; the body is still read.
            self.skipping = [open_tag for open_tag in self.skipping if open_tag != "head"]
        if tag == "title":
            self.in_title = True
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self.in_data = True
            self.data.append("")
        elif tag == "script":
            # Read as data (a video page's description), never run.
            self.in_script = True
            self.scripts.append("")
        if tag in SKIPPED:
            self.skipping.append(tag)
        elif tag in BLOCKS and not self.skipping:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "script":
            self.in_data = False
            self.in_script = False
        if self.skipping and self.skipping[-1] == tag:
            self.skipping.pop()

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        elif self.in_data:
            self.data[-1] += data
        elif self.in_script:
            if len(self.scripts[-1]) < MAX_BYTES:
                self.scripts[-1] += data
        elif not self.skipping:
            self.text.append(data)


def recipes_in(value: Any) -> Iterator[dict[str, Any]]:
    """Recipe objects in a page's JSON-LD, wherever they sit."""
    if isinstance(value, list):
        for item in value:
            yield from recipes_in(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "Recipe" or (isinstance(kind, list) and "Recipe" in kind):
            yield value
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                yield from recipes_in(value[key])


# Where video pages keep the whole description the meta tag cuts short.
PAGE_DATA = (
    ("ytInitialPlayerResponse", ("videoDetails", "title"), ("videoDetails", "shortDescription")),
    ("__INITIAL_STATE__", ("videoData", "title"), ("videoData", "desc")),
)


def page_data(scripts: list[str]) -> list[str]:
    """A video's title and description from the JSON its page assigns to a
    known name, decoded as data."""
    found: list[str] = []
    decoder = json.JSONDecoder()
    for script in scripts:
        for name, *paths in PAGE_DATA:
            match = re.search(re.escape(name) + r"\s*=\s*\{", script)
            if not match:
                continue
            try:
                value, _ = decoder.raw_decode(script, match.end() - 1)
            except ValueError:
                continue
            for path in paths:
                node: Any = value
                for key in path:
                    node = node.get(key) if isinstance(node, dict) else None
                if isinstance(node, str) and node.strip():
                    found.append(node.strip())
    return list(dict.fromkeys(found))


def steps_of(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from steps_of(item)
    elif isinstance(value, dict):
        if value.get("text"):
            yield str(value["text"])
        yield from steps_of(value.get("itemListElement", []))


def squash(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", value)).strip()


def page_text(html: str) -> str:
    """Title, description, recipe data and visible text; empty when the page
    has nothing to read beyond a title."""
    reader = Reader()
    reader.feed(html)
    reader.close()
    title = squash("".join(reader.title))
    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    descriptions = list(
        dict.fromkeys(
            value
            for key in ("description", "og:description", "twitter:description")
            if (value := reader.meta.get(key))
        )
    )
    descriptions += [value for value in page_data(reader.scripts) if value not in descriptions]
    lines += [f"Description: {value}" for value in descriptions]
    found = 0
    for raw in reader.data:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for recipe in recipes_in(data):
            found += 1
            lines.append(f"Recipe: {recipe.get('name', '')}".strip())
            for key in ("description", "recipeYield", "prepTime", "cookTime", "totalTime"):
                if recipe.get(key):
                    lines.append(f"{key}: {recipe[key]}")
            ingredients = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
            if isinstance(ingredients, list) and ingredients:
                lines.append("Ingredients: " + "; ".join(str(item) for item in ingredients))
            steps = [squash(step) for step in steps_of(recipe.get("recipeInstructions", []))]
            if steps:
                lines.append(
                    "Steps: " + " ".join(f"{n}. {step}" for n, step in enumerate(steps, 1))
                )
    visible = squash("".join(reader.text))
    if visible:
        lines.append("Page text: " + visible)
    if not descriptions and not found and len(visible) < 20:
        return ""
    return "\n".join(lines)[:MAX_TEXT]
