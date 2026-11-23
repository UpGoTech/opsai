"""Rename DocType OpsAi Settings → OpsAi Users."""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc

from opsai.patches.v1.migrate_opsai_users_auth import execute as migrate_auth


def execute():
	if not frappe.db.exists("DocType", "OpsAi Settings"):
		return
	if frappe.db.exists("DocType", "OpsAi Users"):
		# Model sync may already have created the new DocType from JSON; drop the empty shell
		# so rename can move the real table and linked data across.
		frappe.delete_doc("DocType", "OpsAi Users", force=True, ignore_permissions=True)
	rename_doc("DocType", "OpsAi Settings", "OpsAi Users", force=True, show_alert=False)
	if frappe.db.exists("DocType", "OpsAi Users"):
		frappe.db.set_value("DocType", "OpsAi Users", "module", "OpsAi", update_modified=False)
	# rename_doc does not rewrite `__Auth.doctype` — passwords would decrypt as empty.
	migrate_auth()
