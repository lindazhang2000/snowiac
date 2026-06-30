"""Workflow orchestration for SnowIaC.

Two flows:

* ``run_intake_flow``: ServiceNow ticket → IntakeAgent → (if valid) CodeGenAgent.
  Pauses at the GitHub PR; waits for human approval + merge.
* ``run_post_deploy_flow``: GitHub Actions callback → VerificationAgent →
  ClosureAgent (or escalation).

The two flows are linked by the ``ticket_id`` and persisted via :mod:`store`.
"""
from __future__ import annotations

import logging
from typing import Any

from .agents import closure, code_generation, intake, verification
from .config import get_settings
from .models import (
    ClosureResult,
    CodeGenResult,
    DeploymentReport,
    IntakeResult,
    ServiceNowTicket,
    VerificationResult,
)
from .store import TicketStore, make_store

log = logging.getLogger(__name__)


_settings = get_settings()
_store: TicketStore = make_store(_settings.database_url or None, _settings.snowiac_db_path)


def get_store() -> TicketStore:
    return _store


# ─── Flows ────────────────────────────────────────────────────────────────────
async def run_intake_flow(ticket: ServiceNowTicket) -> dict[str, Any]:
    """Intake → CodeGen. Returns a dict suitable for HTTP responses."""
    _store.put(ticket)
    _store.set_state(ticket.RITM, "intake", "running")
    _store.log_event(ticket.RITM, "intake", "Ticket received", {"catalog": ticket.Catalog})
    log.info("Intake flow start: %s", ticket.RITM)

    intake_result: IntakeResult = await intake.run(ticket)
    if not intake_result.valid:
        _store.set_state(ticket.RITM, "intake", "rejected")
        _store.log_event(
            ticket.RITM,
            "intake_rejected",
            intake_result.notes or "Rejected by IntakeAgent",
            {"missing_fields": intake_result.missing_fields},
        )
        return {"stage": "intake_rejected", "intake": intake_result.model_dump()}

    _store.log_event(
        ticket.RITM,
        "intake_validated",
        f"Classified as {intake_result.kind.value}",
        {"kind": intake_result.kind.value},
    )
    codegen_result: CodeGenResult = await code_generation.run(intake_result)
    _store.set_state(ticket.RITM, "awaiting_human_merge", "paused")
    _store.log_event(
        ticket.RITM,
        "awaiting_human_merge",
        f"PR opened: {codegen_result.pr_url}",
        {"pr_url": codegen_result.pr_url, "branch": codegen_result.branch},
    )
    return {
        "stage": "awaiting_human_merge",
        "intake": intake_result.model_dump(),
        "codegen": codegen_result.model_dump(),
    }


async def run_post_deploy_flow(report: DeploymentReport) -> dict[str, Any]:
    """Verification → Closure. Triggered by /webhooks/github."""
    ticket = _store.get(report.ticket_id)
    if ticket is None:
        # Webhook may have arrived before the ticket was persisted (race). Do not
        # mark the run as processed, so a retried delivery can still be handled.
        log.error("No stored ticket for %s — cannot verify", report.ticket_id)
        return {"stage": "error", "error": f"ticket {report.ticket_id} not found in store"}

    # Idempotency: GitHub may retry the webhook (or two runs race). A run_id is
    # processed at most once; duplicates are acknowledged but not re-run.
    if not _store.mark_run_processed(report.run_id, report.ticket_id):
        log.info(
            "Duplicate webhook for run_id=%s ticket=%s — ignoring",
            report.run_id,
            report.ticket_id,
        )
        return {"stage": "duplicate_ignored", "run_id": report.run_id}

    _store.set_state(report.ticket_id, "verification", "running")
    _store.log_event(
        report.ticket_id,
        f"deploy_{report.status}",
        f"GitHub Actions run {report.run_id} reported status={report.status}",
        {"run_id": report.run_id, "log_url": report.log_url, "outputs": report.outputs},
    )
    log.info("Post-deploy flow start: %s status=%s", report.ticket_id, report.status)

    try:
        verif_result: VerificationResult = await verification.run(report, ticket)
        _store.log_event(
            report.ticket_id,
            "verified" if verif_result.success else "verification_failed",
            verif_result.summary[:300],
            {"evidence": verif_result.evidence},
        )
        closure_result: ClosureResult = await closure.run(verif_result, ticket)
        final_stage = "complete" if closure_result.closed else "escalated"
        _store.set_state(
            report.ticket_id,
            final_stage,
            "closed" if closure_result.closed else "escalated",
        )
        _store.log_event(
            report.ticket_id,
            final_stage,
            f"Final SNOW state: {closure_result.final_state}",
            {"closed": closure_result.closed, "notes": closure_result.notes},
        )
    except Exception as e:  # noqa: BLE001
        # Flow failed after claiming the run_id. Release it so a retried webhook
        # delivery (same run_id) can re-drive verification/closure, and record
        # the error in the durable state for operators.
        _store.unmark_run_processed(report.run_id)
        _store.set_state(report.ticket_id, "verification", "error")
        _store.log_event(
            report.ticket_id,
            "post_deploy_error",
            f"Post-deploy flow failed: {e}",
            {"run_id": report.run_id},
        )
        log.exception("Post-deploy flow failed for %s — released run for retry", report.ticket_id)
        raise

    return {
        "stage": final_stage,
        "verification": verif_result.model_dump(),
        "closure": closure_result.model_dump(),
    }
