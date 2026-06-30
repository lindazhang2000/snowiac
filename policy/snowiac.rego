package main

# Policy-as-code gate for SnowIaC-generated Terraform.
#
# Evaluated by Conftest against a `terraform show -json plan.json`
# (the planned state of a pull request under azure/**). A single `deny`
# message fails the PR check and blocks the merge.
#
#   conftest test plan.json --policy policy
#
# Rules are intentionally conservative: they encode the guardrails SnowIaC
# is allowed to apply autonomously. Anything outside these bounds requires a
# human to change the policy (with review), not just merge the PR.

# Resource changes that create or update something (ignore pure deletes/no-ops).
changed[r] {
	r := input.resource_changes[_]
	r.change.actions[_] != "delete"
	r.change.actions[_] != "no-op"
}

# Locations SnowIaC is permitted to deploy into.
allowed_locations := {"eastus", "eastus2", "westus2", "westeurope"}

# Upper bound on a single managed disk SnowIaC may provision without escalation.
max_disk_size_gb := 4096

# Every managed/azure resource must carry a snowiac ticket tag for traceability.
deny[msg] {
	r := changed[_]
	startswith(r.type, "azurerm_")
	after := r.change.after
	not after.tags.ritm
	msg := sprintf("%s '%s' is missing required tag 'ritm' (ticket traceability)", [r.type, r.name])
}

# Restrict deployments to approved regions.
deny[msg] {
	r := changed[_]
	loc := lower(r.change.after.location)
	loc != ""
	not allowed_locations[loc]
	msg := sprintf("%s '%s' targets disallowed location '%s' (allowed: %v)", [r.type, r.name, loc, allowed_locations])
}

# Cap managed disk size.
deny[msg] {
	r := changed[_]
	r.type == "azurerm_managed_disk"
	size := r.change.after.disk_size_gb
	size > max_disk_size_gb
	msg := sprintf("azurerm_managed_disk '%s' size %dGB exceeds max %dGB", [r.name, size, max_disk_size_gb])
}

# Never let SnowIaC open SSH/RDP to the world.
deny[msg] {
	r := changed[_]
	r.type == "azurerm_network_security_rule"
	after := r.change.after
	lower(after.access) == "allow"
	lower(after.direction) == "inbound"
	after.source_address_prefix == "*"
	port := {"22", "3389"}
	after.destination_port_range == port[_]
	msg := sprintf("NSG rule '%s' exposes port %s to the internet (source '*')", [r.name, after.destination_port_range])
}
