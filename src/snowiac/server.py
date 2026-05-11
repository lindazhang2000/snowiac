"""FastAPI HTTP server — entry point for ServiceNow + GitHub Actions."""
from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from .config import get_settings
from .models import DeploymentReport, ServiceNowTicket, TicketEnvelope
from .workflow import get_store, run_intake_flow, run_post_deploy_flow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("snowiac.server")

app = FastAPI(title="SnowIaC", version="0.1.0")

_DASHBOARD_HTML = (Path(__file__).parent / "static" / "dashboard.html").read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return _DASHBOARD_HTML


@app.get("/api/tickets")
async def api_tickets() -> dict:
    return {"tickets": get_store().list_tickets()}


@app.get("/api/tickets/{ticket_id}")
async def api_ticket_detail(ticket_id: str) -> dict:
    store = get_store()
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(404, f"ticket {ticket_id} not found")
    return {
        "ticket": ticket.model_dump(),
        "spec": store.get_spec(ticket_id),
        "events": store.get_events(ticket_id),
    }



def _extract_ticket(payload: dict) -> ServiceNowTicket:
    """Accepts either the ServiceNow envelope (`{result:[...]}`) or a bare ticket."""
    if isinstance(payload, dict) and "result" in payload:
        env = TicketEnvelope.model_validate(payload)
        if not env.result:
            raise HTTPException(400, "empty result array")
        return env.result[0]
    return ServiceNowTicket.model_validate(payload)


@app.post("/tickets/intake")
async def tickets_intake(request: Request) -> dict:
    payload = await request.json()
    try:
        ticket = _extract_ticket(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid ticket payload: {e}") from e
    return await run_intake_flow(ticket)


def _verify_hmac(secret: str, body: bytes, signature: str | None) -> None:
    if not signature:
        raise HTTPException(401, "missing signature")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Constant-time comparison; accept "sha256=<hex>" or bare hex.
    candidate = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, candidate):
        raise HTTPException(401, "signature mismatch")


@app.post("/webhooks/github")
async def webhooks_github(request: Request) -> dict:
    body = await request.body()
    s = get_settings()
    if not s.snowiac_use_mocks:
        _verify_hmac(s.webhook_hmac_secret, body, request.headers.get("X-Snowiac-Signature"))

    try:
        report = DeploymentReport.model_validate_json(body)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid deployment report: {e}") from e

    return await run_post_deploy_flow(report)
