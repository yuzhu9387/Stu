"""Async client for the Lark international API."""

import json
from typing import Protocol

import httpx

from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer


class TenantTokenProvider(Protocol):
    async def tenant_access_token(self) -> str: ...

    async def invalidate(self, token: str) -> None: ...


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

    async def send_final(
        self,
        chat_id: str,
        response: FinalAgentResponse,
        actions: tuple[IssuedSuggestedAction, ...],
        locale: Locale,
        *,
        idempotency_key: str = "",
    ) -> None:
        await self._send_card(
            chat_id,
            self._renderer.final(response, actions, locale),
            idempotency_key=idempotency_key,
        )

    async def send_linking_instructions(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None:
        await self._send_card(
            chat_id,
            self._renderer.linking_instructions(locale),
            idempotency_key=idempotency_key,
        )

    async def send_linked(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None:
        await self._send_card(
            chat_id,
            self._renderer.linked(locale),
            idempotency_key=idempotency_key,
        )

    async def send_failure(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None:
        await self._send_card(
            chat_id,
            self._renderer.failure(locale),
            idempotency_key=idempotency_key,
        )

    async def _send_card(
        self,
        chat_id: str,
        card: object,
        *,
        idempotency_key: str = "",
    ) -> None:
        body = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, separators=(",", ":"), ensure_ascii=False),
            **({"uuid": idempotency_key} if idempotency_key else {}),
        }
        for attempt in range(2):
            token = await self._token_provider.tenant_access_token()
            try:
                response = await self._http.post(
                    f"{self._base_url}/open-apis/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers={"Authorization": f"Bearer {token}"},
                    json=body,
                )
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                raise LarkAPIError("Lark message delivery failed") from None
            auth_rejected = response.status_code == 401 or (
                isinstance(payload, dict)
                and payload.get("code") in {99991663, 99991664, 99991668, 99991671}
            )
            if auth_rejected and attempt == 0:
                await self._token_provider.invalidate(token)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPError:
                raise LarkAPIError("Lark message delivery failed") from None
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise LarkAPIError("Lark message delivery failed")
            return
        raise LarkAPIError("Lark message delivery failed")
