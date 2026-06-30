"""Closure agent: closes the ServiceNow ticket with a final summary.

Also emails the requester when the request arrived via email (or any time an
EmailAddress is present and SMTP is configured). This makes closure work for
non-ServiceNow channels: with no SNOW instance the ServiceNow client is a mock
that just logs, while the email reply becomes the real closure notification.
"""
from __future__ import annotations

import logging

from ..models import ClosureResult, ServiceNowTicket, VerificationResult
from ..services import notifier, servicenow

log = logging.getLogger(__name__)


async def run(
    verification: VerificationResult,
    ticket: ServiceNowTicket | None = None,
) -> ClosureResult:
    snow = servicenow.build_client()
    mailer = notifier.build_notifier()
    requester_email = ticket.EmailAddress if ticket else ""

    if not verification.success:
        # Verification already escalated; do not auto-close.
        notes = "Verification failed — left open for cloud admin."
        if requester_email:
            await mailer.send(
                requester_email,
                f"[SnowIaC] {verification.ticket_id} needs review",
                f"Your request could not be auto-verified and was routed to a "
                f"cloud admin.\n\n{verification.summary}",
            )
        return ClosureResult(
            ticket_id=verification.ticket_id,
            closed=False,
            final_state="Admin Review",
            notes=notes,
        )

    summary = (
        f"[SnowIaC] Change deployed and verified. {verification.summary} "
        f"Closing ticket as Complete."
    )
    snow_ok = True
    try:
        await snow.add_comment(verification.ticket_id, summary)
        await snow.update_state(
            verification.ticket_id, state="Closed Complete", stage="Request Complete"
        )
    except Exception as e:  # noqa: BLE001
        # ServiceNow being unreachable must not crash closure — the change is
        # already verified live. Fall back to the email notification and flag
        # the ticket for a manual SNOW sync.
        snow_ok = False
        log.error("ServiceNow close failed for %s: %s", verification.ticket_id, e)

    if requester_email:
        await mailer.send(
            requester_email,
            f"[SnowIaC] {verification.ticket_id} complete",
            summary,
        )

    notes = summary if snow_ok else f"{summary} (ServiceNow update failed — sync manually)"
    return ClosureResult(
        ticket_id=verification.ticket_id,
        closed=True,
        final_state="Closed Complete" if snow_ok else "Closed Complete (SNOW sync pending)",
        notes=notes,
    )
