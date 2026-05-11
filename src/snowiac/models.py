"""Pydantic models for ServiceNow tickets and inter-agent messages."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── ServiceNow ticket (matches Sample_ER_*.json shape) ───────────────────────
class PayloadField(BaseModel):
    RequestFieldName: str
    PayloadTokenValue: str


class ServiceNowTicket(BaseModel):
    Request: str
    RITM: str
    RequestedFor: str
    EmailAddress: str = ""
    UserID: str = ""
    Manager: str = ""
    Location: str = ""
    Department: str = ""
    State: str = ""
    Stage: str = ""
    Catalog: str
    ShortDescription: str = ""
    CreatedDate: str = ""
    CreatedBy: str = ""
    ClosedDate: str = ""
    ManagerID: str = ""
    Payload: list[PayloadField] = Field(default_factory=list)

    def field(self, name: str) -> str | None:
        for p in self.Payload:
            if p.RequestFieldName == name:
                return p.PayloadTokenValue
        return None

    def fields(self, name: str) -> list[str]:
        return [p.PayloadTokenValue for p in self.Payload if p.RequestFieldName == name]


class TicketEnvelope(BaseModel):
    """ServiceNow exports shape: { "result": [ ticket ] }."""
    result: list[ServiceNowTicket]


# ─── Request classification ───────────────────────────────────────────────────
class RequestKind(str, Enum):
    AZURE_INFRA_CHANGE = "azure_infra_change"
    UNKNOWN = "unknown"


# ─── Agent results ────────────────────────────────────────────────────────────
class IntakeResult(BaseModel):
    ticket_id: str
    valid: bool
    kind: RequestKind = RequestKind.UNKNOWN
    missing_fields: list[str] = Field(default_factory=list)
    notes: str = ""
    ticket: ServiceNowTicket


class CodeGenResult(BaseModel):
    ticket_id: str
    pr_url: str
    pr_number: int
    branch: str
    files: list[str]
    notes: str = ""


class DeploymentReport(BaseModel):
    ticket_id: str
    status: Literal["applied", "failed"]
    run_id: str
    log_url: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    ticket_id: str
    success: bool
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ClosureResult(BaseModel):
    ticket_id: str
    closed: bool
    final_state: str
    notes: str = ""
