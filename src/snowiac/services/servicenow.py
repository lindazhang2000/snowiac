"""ServiceNow client. Provides a real REST adapter and an in-memory mock."""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from ..config import get_settings
from ..models import ServiceNowTicket

log = logging.getLogger(__name__)


class ServiceNowClient(Protocol):
    async def add_comment(self, ticket_id: str, comment: str) -> None: ...
    async def update_state(self, ticket_id: str, state: str, stage: str | None = None) -> None: ...
    async def get(self, ticket_id: str) -> ServiceNowTicket | None: ...


class HttpServiceNowClient:
    """Real ServiceNow Table API client (sn_customerservice or sc_req_item)."""

    def __init__(self, base_url: str, user: str, password: str, table: str = "sc_req_item"):
        self._base = base_url.rstrip("/")
        self._auth = (user, password)
        self._table = table
        self._sys_id_cache: dict[str, str] = {}

    async def _resolve_sys_id(self, ticket_id: str) -> str | None:
        """Accept either a sys_id (32 hex chars) or a number like RITM0654928."""
        if len(ticket_id) == 32 and all(ch in "0123456789abcdef" for ch in ticket_id.lower()):
            return ticket_id
        if ticket_id in self._sys_id_cache:
            return self._sys_id_cache[ticket_id]
        url = f"{self._base}/api/now/table/{self._table}"
        params = {"sysparm_query": f"number={ticket_id}", "sysparm_fields": "sys_id", "sysparm_limit": "1"}
        async with httpx.AsyncClient(auth=self._auth, timeout=30) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            results = r.json().get("result", [])
        if not results:
            return None
        sys_id = results[0]["sys_id"]
        self._sys_id_cache[ticket_id] = sys_id
        return sys_id

    async def add_comment(self, ticket_id: str, comment: str) -> None:
        sys_id = await self._resolve_sys_id(ticket_id)
        if not sys_id:
            log.warning("ServiceNow ticket %s not found — skipping comment", ticket_id)
            return
        url = f"{self._base}/api/now/table/{self._table}/{sys_id}"
        async with httpx.AsyncClient(auth=self._auth, timeout=30) as c:
            r = await c.patch(url, json={"comments": comment})
            r.raise_for_status()

    async def update_state(self, ticket_id: str, state: str, stage: str | None = None) -> None:
        sys_id = await self._resolve_sys_id(ticket_id)
        if not sys_id:
            log.warning("ServiceNow ticket %s not found — skipping state update", ticket_id)
            return
        url = f"{self._base}/api/now/table/{self._table}/{sys_id}"
        body: dict[str, str] = {"state": state}
        if stage:
            body["stage"] = stage
        async with httpx.AsyncClient(auth=self._auth, timeout=30) as c:
            r = await c.patch(url, json=body)
            r.raise_for_status()

    async def get(self, ticket_id: str) -> ServiceNowTicket | None:
        sys_id = await self._resolve_sys_id(ticket_id)
        if not sys_id:
            return None
        url = f"{self._base}/api/now/table/{self._table}/{sys_id}"
        async with httpx.AsyncClient(auth=self._auth, timeout=30) as c:
            r = await c.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json().get("result")
            return ServiceNowTicket.model_validate(data) if data else None


class MockServiceNowClient:
    """In-memory mock used when SNOWIAC_USE_MOCKS=true."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.tickets: dict[str, ServiceNowTicket] = {}

    async def add_comment(self, ticket_id: str, comment: str) -> None:
        log.info("[MOCK SNOW] %s comment: %s", ticket_id, comment)
        self.events.append(("comment", ticket_id, comment))

    async def update_state(self, ticket_id: str, state: str, stage: str | None = None) -> None:
        log.info("[MOCK SNOW] %s state=%s stage=%s", ticket_id, state, stage)
        self.events.append(("state", ticket_id, f"{state}/{stage or ''}"))

    async def get(self, ticket_id: str) -> ServiceNowTicket | None:
        return self.tickets.get(ticket_id)


def build_client() -> ServiceNowClient:
    s = get_settings()
    if s.snowiac_use_mocks or not s.snow_instance_url:
        return MockServiceNowClient()
    return HttpServiceNowClient(s.snow_instance_url, s.snow_user, s.snow_password)
