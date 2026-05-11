"""Intake agent: validates required ServiceNow fields and classifies the request.

If invalid, posts a comment to ServiceNow asking the requester to resubmit.
"""
from __future__ import annotations

import json
import logging

from agent_framework import Agent

from ..llm import get_chat_client
from ..models import IntakeResult, RequestKind, ServiceNowTicket
from ..services import servicenow

log = logging.getLogger(__name__)

INSTRUCTIONS = """
You are the Intake Agent for an infrastructure-as-code automation pipeline.

You receive a ServiceNow ticket as JSON. Decide:

1. `kind`: one of `azure_infra_change` or `unknown`.
   - Use the `Catalog` field as the primary signal.
2. `valid`: whether the ticket has every field required for that kind.
3. `missing_fields`: names of any missing/empty required fields.
4. `notes`: a short, customer-friendly explanation (1-3 sentences).

REQUIRED fields:
- `azure_infra_change`: Enter a detailed description of the request, Business Application

Respond with ONLY a JSON object of the form:
{"kind": "...", "valid": true|false, "missing_fields": [...], "notes": "..."}
""".strip()


# Hard-coded required-field map mirrors the LLM rules above so the agent can
# also operate deterministically when the LLM is unavailable.
_REQUIRED: dict[RequestKind, list[str]] = {
    RequestKind.AZURE_INFRA_CHANGE: [
        "Enter a detailed description of the request",
        "Business Application",
    ],
}


def _classify(ticket: ServiceNowTicket) -> RequestKind:
    cat = ticket.Catalog.lower()
    if "azure" in cat or "cloud" in cat:
        return RequestKind.AZURE_INFRA_CHANGE
    return RequestKind.UNKNOWN


def _check_required(ticket: ServiceNowTicket, kind: RequestKind) -> list[str]:
    if kind not in _REQUIRED:
        return ["<unsupported request type>"]
    missing: list[str] = []
    for name in _REQUIRED[kind]:
        val = ticket.field(name)
        if not val or val.lower() in {"false", ""}:
            missing.append(name)
    return missing


async def run(ticket: ServiceNowTicket) -> IntakeResult:
    """Run the intake agent. Falls back to deterministic logic if LLM unavailable."""
    kind = _classify(ticket)
    missing = _check_required(ticket, kind)
    notes = ""

    try:
        client = get_chat_client()
        async with Agent(client=client, name="IntakeAgent", instructions=INSTRUCTIONS) as agent:
            response = await agent.run(ticket.model_dump_json())
            try:
                parsed = json.loads(response.text or "{}")
                kind = RequestKind(parsed.get("kind", kind.value))
                # Trust LLM for missing_fields only when it found more than the deterministic check.
                llm_missing = parsed.get("missing_fields") or []
                if llm_missing:
                    missing = list({*missing, *llm_missing})
                notes = parsed.get("notes", "") or ""
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("IntakeAgent JSON parse failed: %s — using deterministic result", e)
    except Exception as e:  # noqa: BLE001
        log.warning("IntakeAgent LLM call failed (%s) — using deterministic logic", e)

    valid = not missing and kind is not RequestKind.UNKNOWN
    if not notes:
        notes = (
            "Ticket validated and routed for code generation."
            if valid
            else f"Cannot proceed. Missing or invalid: {', '.join(missing) or 'request type'}."
        )

    result = IntakeResult(
        ticket_id=ticket.RITM,
        valid=valid,
        kind=kind,
        missing_fields=missing,
        notes=notes,
        ticket=ticket,
    )

    # Side-effect: if invalid, ask the requester to resubmit.
    if not valid:
        snow = servicenow.build_client()
        try:
            await snow.add_comment(
                ticket.RITM,
                f"[SnowIaC Intake] {notes} Please update the ticket and resubmit.",
            )
            await snow.update_state(ticket.RITM, state="Pending", stage="Awaiting Info")
        except Exception as e:  # noqa: BLE001
            log.warning("ServiceNow update failed for %s (%s) — continuing", ticket.RITM, e)

    return result
