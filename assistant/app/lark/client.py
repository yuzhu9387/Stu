from __future__ import annotations
import json
import time
from typing import Optional, Dict, Any
import httpx

LARK_BASE_URL = "https://open.larksuite.com/open-apis"


class LarkClient:
    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = httpx.AsyncClient(base_url=LARK_BASE_URL, timeout=30.0)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def get_tenant_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = await self._http.post(
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["tenant_access_token"]
        self._token_expires_at = time.time() + data.get("expire", 7200)
        return self._token

    async def _headers(self) -> Dict[str, str]:
        token = await self.get_tenant_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def send_text(self, user_id: str, text: str) -> Dict[str, Any]:
        headers = await self._headers()
        body = {"receive_id": user_id, "msg_type": "text", "content": json.dumps({"text": text})}
        resp = await self._http.post("/im/v1/messages?receive_id_type=user_id", headers=headers, json=body)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def send_card(self, user_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        headers = await self._headers()
        body = {"receive_id": user_id, "msg_type": "interactive", "content": json.dumps(card)}
        resp = await self._http.post("/im/v1/messages?receive_id_type=user_id", headers=headers, json=body)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def reply_text(self, message_id: str, text: str) -> Dict[str, Any]:
        headers = await self._headers()
        body = {"msg_type": "text", "content": json.dumps({"text": text})}
        resp = await self._http.post(f"/im/v1/messages/{message_id}/reply", headers=headers, json=body)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def reply_card(self, message_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        headers = await self._headers()
        body = {"msg_type": "interactive", "content": json.dumps(card)}
        resp = await self._http.post(f"/im/v1/messages/{message_id}/reply", headers=headers, json=body)
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def close(self) -> None:
        await self._http.aclose()
