"""Verification agent: confirms the deployed change took effect in Azure."""
from __future__ import annotations

import logging

from agent_framework import Agent

from ..llm import get_chat_client
from ..models import DeploymentReport, RequestKind, ServiceNowTicket, VerificationResult
from ..services import azure_verifier, servicenow

log = logging.getLogger(__name__)

INSTRUCTIONS = """
You are the Verification Agent. You receive a deployment report and the
observed state of the target resource. Decide if the change met the request
in the original ServiceNow ticket. Reply with a single JSON object:

{"success": true|false, "summary": "1-2 sentence explanation"}
""".strip()


async def run(report: DeploymentReport, ticket: ServiceNowTicket) -> VerificationResult:
    evidence: dict = {}
    deterministic_ok = report.status == "applied"
    failed_checks: list[dict] = []

    # Look up the verification spec persisted by CodeGen (smart path).
    spec: dict | None = None
    try:
        from ..workflow import get_store

        spec = get_store().get_spec(ticket.RITM)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read verification spec for %s: %s", ticket.RITM, e)

    catalog = ticket.Catalog.lower()

    if spec and ("azure" in catalog or "cloud" in catalog) and deterministic_ok:
        # Spec-driven path: assert each attribute the CodeGen agent declared.
        evidence = azure_verifier.verify_spec(spec)
        deterministic_ok = bool(evidence.get("passed"))
        failed_checks = [c for c in evidence.get("checks", []) if not c.get("passed")]
        log.info(
            "Spec-driven verify for %s: passed=%s checks=%s",
            ticket.RITM,
            deterministic_ok,
            evidence.get("checks"),
        )
    elif "azure" in catalog or "cloud" in catalog:
        # Legacy fallback: probe disk by RG/name from the deployment outputs.
        rg = report.outputs.get("resource_group", "snowiac-rg")
        disk = report.outputs.get("disk_name", "sql1-data-disk")
        evidence = azure_verifier.verify_disk(rg, disk)
        if evidence.get("found") is False:
            deterministic_ok = False
        desc = ticket.field("Enter a detailed description of the request") or ""
        if "5000" in desc and evidence.get("iops"):
            deterministic_ok = deterministic_ok and evidence["iops"] >= 5000
        if "350" in desc and evidence.get("mbps"):
            deterministic_ok = deterministic_ok and evidence["mbps"] >= 350

    summary = (
        f"Deployment {report.status}. Observed: {evidence}."
        if evidence
        else f"Deployment {report.status}."
    )

    try:
        client = get_chat_client()
        prompt = (
            f"Ticket: {ticket.model_dump_json()}\n"
            f"Deployment: {report.model_dump_json()}\n"
            f"Verification spec: {spec}\n"
            f"Observed state + check results: {evidence}\n"
            f"Deterministic verdict: {'PASS' if deterministic_ok else 'FAIL'}\n"
        )
        async with Agent(
            client=client, name="VerificationAgent", instructions=INSTRUCTIONS
        ) as agent:
            response = await agent.run(prompt)
            text = (response.text or "").strip()
            if text:
                summary = text
    except Exception as e:  # noqa: BLE001
        log.warning("VerificationAgent LLM call failed (%s) — using deterministic summary", e)

    success = deterministic_ok

    if not success:
        snow = servicenow.build_client()
        check_lines = "\n".join(
            f"  - {c['attribute']} expected {c['op']} {c['expected']}, observed {c['actual']}"
            for c in failed_checks
        )
        await snow.add_comment(
            ticket.RITM,
            f"[SnowIaC Verification] Issue detected after deployment: {summary}\n"
            + (f"Failing checks:\n{check_lines}\n" if check_lines else "")
            + f"Cloud admin (manager: {ticket.Manager}) please review.",
        )
        await snow.update_state(ticket.RITM, state="Work in Progress", stage="Admin Review")

    return VerificationResult(
        ticket_id=ticket.RITM, success=success, summary=summary, evidence=evidence
    )
