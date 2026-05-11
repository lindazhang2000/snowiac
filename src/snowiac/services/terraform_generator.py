"""Renders Terraform from a ServiceNow ticket using Jinja2 templates."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..config import get_settings
from ..models import RequestKind, ServiceNowTicket

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "terraform_templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", value.lower()).strip("_") or "resource"


def render(
    ticket: ServiceNowTicket,
    kind: RequestKind,
    azure_params: dict | None = None,
) -> dict[str, str]:
    """Returns {relative_path: file_content}.

    For ``AZURE_INFRA_CHANGE`` callers SHOULD pass the LLM-extracted
    ``azure_params`` dict (see ``parameter_extractor.AzureDiskParams``). When
    omitted, the renderer falls back to regex extraction with safe defaults.
    """
    if kind is RequestKind.AZURE_INFRA_CHANGE:
        return _render_azure_disk(ticket, azure_params)
    raise ValueError(f"Unsupported request kind: {kind}")


# ─── Azure infra change (disk IOPS / throughput) ──────────────────────────────
_NUM = re.compile(r"(\d+)\s*(?:mbps|iops)?", re.I)


def _extract_change(description: str) -> dict[str, int]:
    """Naive extraction of target IOPS / throughput from free-form text.

    The CodeGen agent's LLM call is the source of truth for ambiguous tickets;
    this helper provides a deterministic fallback.
    """
    out: dict[str, int] = {}
    # Prefer "to N mbps" / "= N mbps" (target value) over "from N mbps" (current).
    m = re.search(r"(?:to|=)\s*(\d+)\s*mbps", description, re.I)
    if not m:
        m = re.search(r"(\d+)\s*mbps", description, re.I)
    if m:
        out["throughput_mbps"] = int(m.group(1))
    m = re.search(r"(?:to|=)\s*(\d+)\s*iops", description, re.I)
    if not m:
        m = re.search(r"iops\s*(?:to|=)\s*(\d+)", description, re.I)
    if not m:
        m = re.search(r"(\d+)\s*iops", description, re.I)
    if m:
        out["iops"] = int(m.group(1))
    return out


def _render_azure_disk(
    t: ServiceNowTicket, params: dict | None = None
) -> dict[str, str]:
    desc = t.field("Enter a detailed description of the request") or t.ShortDescription
    settings = get_settings()

    if params:
        target_vm = params["vm_name"]
        disk_name = params["disk_name"]
        resource_group = params["resource_group_name"]
        location = params["location"]
        disk_size_gb = params["disk_size_gb"]
        iops = params["target_iops"]
        throughput = params["target_mbps"]
    else:
        change = _extract_change(desc)
        target_vm = "sql1"
        m = re.search(r"new vms?:\s*([a-z0-9_-]+)", desc, re.I)
        if m:
            target_vm = m.group(1)
        iops = change.get("iops", 5000)
        throughput = change.get("throughput_mbps", 350)
        disk_name = f"{target_vm}-data"
        resource_group = settings.azure_default_resource_group
        location = settings.azure_default_location
        disk_size_gb = 1024

    base = f"azure/{_slug(t.RITM)}"
    main_tpl = _env.get_template("azure_disk_change.tf.j2")
    tfvars_tpl = _env.get_template("azure_disk_change.auto.tfvars.j2")
    backend_tpl = _env.get_template("azure_backend.tf.j2")

    main_tf = main_tpl.render(
        ticket_id=t.RITM,
        vm_name=target_vm,
        iops=iops,
        throughput_mbps=throughput,
        requested_for=t.RequestedFor,
        description=desc.replace("\n", " ").replace("\r", " ")[:200],
    )
    tfvars = tfvars_tpl.render(
        ticket_id=t.RITM,
        subscription_id=settings.azure_subscription_id or "00000000-0000-0000-0000-000000000000",
        resource_group_name=resource_group,
        disk_name=disk_name,
        location=location,
        disk_size_gb=disk_size_gb,
    )
    backend_tf = backend_tpl.render(ticket_id=t.RITM)

    return {
        f"{base}/main.tf": main_tf,
        f"{base}/terraform.auto.tfvars": tfvars,
        f"{base}/backend.tf": backend_tf,
    }
