"""Run the intake → codegen flow against a local sample JSON file.

Usage:
    python scripts/run_sample.py Sample_ER_Azure_Cloud_Admin.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure src/ is on the path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from snowiac.models import ServiceNowTicket, TicketEnvelope  # noqa: E402
from snowiac.workflow import run_intake_flow  # noqa: E402


async def _main(path: str) -> None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "result" in payload:
        ticket = TicketEnvelope.model_validate(payload).result[0]
    else:
        ticket = ServiceNowTicket.model_validate(payload)

    result = await run_intake_flow(ticket)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: run_sample.py <ticket.json>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(_main(sys.argv[1]))
