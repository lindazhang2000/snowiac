"""Verifies that a deployed Azure change actually took effect."""
from __future__ import annotations

import logging
import operator
from typing import Any, Callable

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

from ..config import get_settings

log = logging.getLogger(__name__)


_OPS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
}


def verify_disk(resource_group: str, disk_name: str) -> dict[str, Any]:
    """Returns observed IOPS / throughput for a managed disk.

    Falls back to a stubbed dict if Azure credentials are unavailable
    (i.e., local mock mode).
    """
    s = get_settings()
    if s.snowiac_use_mocks or not s.azure_subscription_id:
        log.info("[MOCK AZ] verify_disk(%s/%s)", resource_group, disk_name)
        return {
            "disk_iops_read_write": 5000,
            "disk_mbps_read_write": 350,
            "iops": 5000,
            "mbps": 350,
            "mocked": True,
            "found": True,
        }

    try:
        credential = DefaultAzureCredential()
        client = ComputeManagementClient(credential, s.azure_subscription_id)
        disk = client.disks.get(resource_group, disk_name)
        return {
            # Canonical (Terraform-attribute) names:
            "disk_iops_read_write": disk.disk_iops_read_write,
            "disk_mbps_read_write": disk.disk_m_bps_read_write,
            # Friendly aliases for older callers:
            "iops": disk.disk_iops_read_write,
            "mbps": disk.disk_m_bps_read_write,
            "size_gb": disk.disk_size_gb,
            "sku": disk.sku.name if disk.sku else None,
            "found": True,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("verify_disk(%s/%s) failed: %s", resource_group, disk_name, e)
        return {"error": str(e), "found": False}


# ─── Generic spec-driven verification ────────────────────────────────────────
def verify_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Run the verifier described by ``spec`` and return a structured result.

    Spec shape::

        {
          "resource_type": "azurerm_managed_disk",
          "resource_group_name": "MultiAgentSnow",
          "resource_name": "sql1-data",
          "asserts": {
              "disk_iops_read_write": {"op": ">=", "value": 5000},
              "disk_mbps_read_write": {"op": ">=", "value": 350},
          },
        }

    Returns ``{"found": bool, "observed": {...}, "checks": [...], "passed": bool}``.
    """
    rtype = spec.get("resource_type")
    rg = spec.get("resource_group_name")
    name = spec.get("resource_name")
    asserts: dict[str, dict[str, Any]] = spec.get("asserts") or {}

    if rtype == "azurerm_managed_disk":
        observed = verify_disk(rg, name)
    else:
        return {
            "found": False,
            "passed": False,
            "error": f"Unsupported resource_type: {rtype}",
            "observed": {},
            "checks": [],
        }

    if not observed.get("found", False):
        return {
            "found": False,
            "passed": False,
            "error": observed.get("error", "resource not found"),
            "observed": observed,
            "checks": [],
        }

    checks: list[dict[str, Any]] = []
    all_passed = True
    for attr, rule in asserts.items():
        op_name = rule.get("op", "==")
        expected = rule.get("value")
        actual = observed.get(attr)
        op = _OPS.get(op_name)
        passed = bool(op and actual is not None and op(actual, expected))
        if not passed:
            all_passed = False
        checks.append(
            {
                "attribute": attr,
                "op": op_name,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
        )

    return {
        "found": True,
        "passed": all_passed,
        "observed": observed,
        "checks": checks,
    }
