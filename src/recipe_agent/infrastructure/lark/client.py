"""Async client for the Lark international API."""

import json
from typing import Protocol

import httpx

from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer


class TenantTokenProvider(Protocol):
    async def tenant_access_token(self) -> str: ...


class LarkAPIError(RuntimeError):
    """The Lark API rejected a message."""


class LarkClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        token_provider: TenantTokenProvider,
        renderer: LarkCardRenderer,
        base_url: str = "https://open.larksuite.com",
    ) -> None:
        self._http = http
        self._token_provider = token_provider
        self._renderer = renderer
        self._base_url = base_url.rstrip("/")

    async def send_progress(self, chat_id: str, progress: AgentProgress, locale: Locale) -> None:
        await self._send_card(chat_id, self._renderer.progress(progress, locale))

    async def send_outcome(self, chat_id: str, outcome: AgentOutcome, locale: Locale) -> None:
        await self._send_card(chat_id, self._renderer.outcome(outcome, locale))

    async def _send_card(self, chat_id: str, card: object) -> None:
        token = await self._token_provider.tenant_access_token()
        response = await self._http.post(
            f"{self._base_url}/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, separators=(",", ":"), ensure_ascii=False),
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise LarkAPIError(str(payload.get("msg", "Lark rejected the message")))
