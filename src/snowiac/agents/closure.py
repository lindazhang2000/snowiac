"""Closure agent: closes the ServiceNow ticket with a final summary."""
from __future__ import annotations

import logging

from ..models import ClosureResult, VerificationResult
from ..services import servicenow

log = logging.getLogger(__name__)


async def run(verification: VerificationResult) -> ClosureResult:
    snow = servicenow.build_client()

    if not verification.success:
        # Verification already escalated; do not auto-close.
        return ClosureResult(
            ticket_id=verification.ticket_id,
            closed=False,
            final_state="Admin Review",
            notes="Verification failed — left open for cloud admin.",
        )

    summary = (
        f"[SnowIaC] Change deployed and verified. {verification.summary} "
        f"Closing ticket as Complete."
    )
    await snow.add_comment(verification.ticket_id, summary)
    await snow.update_state(
        verification.ticket_id, state="Closed Complete", stage="Request Complete"
    )

    return ClosureResult(
        ticket_id=verification.ticket_id,
        closed=True,
        final_state="Closed Complete",
        notes=summary,
    )
