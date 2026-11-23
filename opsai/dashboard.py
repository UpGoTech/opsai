# Copyright (c) 2026, OpsAi and contributors
# License: MIT. See LICENSE

"""Number-card helpers for the OpsAi workspace home."""

from __future__ import annotations

import frappe
from frappe import _


def _can_read_settings() -> bool:
	return bool(frappe.has_permission("OpsAi Users", "read"))


@frappe.whitelist()
@frappe.read_only()
def agents_offline(filters=None):
	"""Assigned Hermes agents that are not Connected (Disconnected or never signed in)."""
	if not _can_read_settings():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	total = frappe.db.count("OpsAi Users")
	live = frappe.db.count("OpsAi Users", {"connection_status": "Connected"})
	return {"value": max(total - live, 0)}
