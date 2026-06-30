package main

# Policy-as-code gate for SnowIaC-generated Terraform.
#
# Evaluated by Conftest against the Terraform HCL directly (hermetic, no cloud
# credentials and no remote state needed):
#
#   conftest test azure/<ticket> --parser hcl2 --policy policy
#
# A single `deny` message fails the PR check and blocks the merge.
#
# NOTE: values sourced from variables/tfvars (e.g. location, disk_size_gb) are
# `${var.*}` references here — they are only resolved at plan time, so they are
# intentionally NOT asserted in this static gate. Tags and literal attributes
# (iops/mbps, inline NSG rules) ARE statically checkable and enforced below.

# Every resource block as [type, name, body].
resource_bodies[[rtype, rname, body]] {
	body := input.resource[rtype][rname]
}

# Throughput caps SnowIaC may set on a managed disk without escalation.
max_disk_iops := 160000

max_disk_mbps := 4000

# Every azurerm resource must carry governance tags for traceability.
deny[msg] {
	[rtype, rname, body] := resource_bodies[_]
	startswith(rtype, "azurerm_")
	not body.tags.snow_ticket
	msg := sprintf("%s.%s is missing required tag 'snow_ticket' (ticket traceability)", [rtype, rname])
}

deny[msg] {
	[rtype, rname, body] := resource_bodies[_]
	startswith(rtype, "azurerm_")
	not body.tags.managed_by
	msg := sprintf("%s.%s is missing required tag 'managed_by'", [rtype, rname])
}

# Cap managed-disk IOPS (literal values only).
deny[msg] {
	[_, rname, body] := resource_bodies[_]
	iops := body.disk_iops_read_write
	is_number(iops)
	iops > max_disk_iops
	msg := sprintf("azurerm_managed_disk.%s disk_iops_read_write=%d exceeds cap %d", [rname, iops, max_disk_iops])
}

# Cap managed-disk throughput (literal values only).
deny[msg] {
	[_, rname, body] := resource_bodies[_]
	mbps := body.disk_mbps_read_write
	is_number(mbps)
	mbps > max_disk_mbps
	msg := sprintf("azurerm_managed_disk.%s disk_mbps_read_write=%d exceeds cap %d", [rname, mbps, max_disk_mbps])
}

# Never let SnowIaC open SSH/RDP to the world via an inline NSG rule.
deny[msg] {
	[_, rname, body] := resource_bodies[_]
	lower(body.access) == "allow"
	lower(body.direction) == "inbound"
	body.source_address_prefix == "*"
	mgmt_port(body.destination_port_range)
	msg := sprintf("NSG rule %s exposes a management port to the internet (source '*')", [rname])
}

mgmt_port(p) {
	p == "22"
}

mgmt_port(p) {
	p == "3389"
}
