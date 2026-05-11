"""LLM-based structured extractor for Azure disk-change tickets.

Replaces fragile regex parsing of the free-form description with a
strict-JSON call to the Foundry chat model. Falls back to regex/defaults
when the LLM is unreachable or returns invalid JSON.
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..llm import get_chat_client
from ..models import ServiceNowTicket

log = logging.getLogger(__name__)


class AzureDiskParams(BaseModel):
    vm_name: str = Field(..., description="Short VM hostname, e.g. 'sql1'.")
    disk_name: str = Field(..., description="Managed disk resource name in Azure.")
    resource_group_name: str = Field(..., description="Azure resource group containing the disk.")
    location: str = Field(..., description="Azure region, e.g. 'eastus'.")
    disk_size_gb: int = Field(..., ge=1, le=65536)
    target_iops: int = Field(..., ge=1)
    target_mbps: int = Field(..., ge=1)


_EXTRACT_INSTRUCTIONS = """\
You extract Azure managed-disk change parameters from a ServiceNow ticket.

Return ONLY a single JSON object (no markdown, no prose) with EXACTLY these keys:
  vm_name              string  - target VM short name
  disk_name            string  - data disk resource name (often "<vm>-data")
  resource_group_name  string  - Azure resource group; use "{rg_default}" if the
                                  ticket does not specify one
  location             string  - Azure region; use "{loc_default}" if unspecified
  disk_size_gb         integer - existing disk size in GB; if not stated, use 1024
  target_iops          integer - the NEW IOPS the user is requesting (not the
                                  current value they are migrating away from)
  target_mbps          integer - the NEW throughput in MB/s (target, not current)

Rules:
- Distinguish "from N" (current) vs "to N" / "increase to N" (target). Always
  pick the TARGET number for target_iops and target_mbps.
- Never invent values you cannot derive from the ticket; use the defaults above.
- Output must be valid JSON parseable by json.loads. No trailing commas. No
  comments. No explanation text.
"""


def _regex_fallback(description: str, settings) -> dict:
    """Deterministic fallback when the LLM call fails."""
    out = {
        "vm_name": "sql1",
        "disk_name": "sql1-data",
        "resource_group_name": settings.azure_default_resource_group,
        "location": settings.azure_default_location,
        "disk_size_gb": 1024,
        "target_iops": 5000,
        "target_mbps": 350,
    }
    m = re.search(r"new vms?:\s*([a-z0-9_-]+)", description, re.I)
    if m:
        out["vm_name"] = m.group(1)
        out["disk_name"] = f"{m.group(1)}-data"
    m = re.search(r"(?:to|=)\s*(\d+)\s*mbps", description, re.I) or re.search(
        r"(\d+)\s*mbps", description, re.I
    )
    if m:
        out["target_mbps"] = int(m.group(1))
    m = (
        re.search(r"(?:to|=)\s*(\d+)\s*iops", description, re.I)
        or re.search(r"iops\s*(?:to|=)\s*(\d+)", description, re.I)
        or re.search(r"(\d+)\s*iops", description, re.I)
    )
    if m:
        out["target_iops"] = int(m.group(1))
    return out


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # remove leading ```json or ``` and trailing ```
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def extract_azure_disk_params(ticket: ServiceNowTicket) -> AzureDiskParams:
    settings = get_settings()
    description = (
        ticket.field("Enter a detailed description of the request")
        or ticket.ShortDescription
        or ""
    )
    instructions = _EXTRACT_INSTRUCTIONS.format(
        rg_default=settings.azure_default_resource_group,
        loc_default=settings.azure_default_location,
    )

    try:
        from agent_framework import Agent  # local import to keep startup light

        client = get_chat_client()
        async with Agent(
            client=client, name="DiskParamExtractor", instructions=instructions
        ) as agent:
            response = await agent.run(f"Ticket description:\n{description}")
        raw = _strip_code_fence(response.text or "")
        data = json.loads(raw)
        return AzureDiskParams.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("Extractor LLM returned invalid JSON (%s) — using regex fallback", e)
    except Exception as e:  # noqa: BLE001
        log.warning("Extractor LLM call failed (%s) — using regex fallback", e)

    return AzureDiskParams.model_validate(_regex_fallback(description, settings))
