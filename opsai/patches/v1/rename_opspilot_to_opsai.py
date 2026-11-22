"""One-time migrate: rename legacy Module Def / DocType / app rows to OpsAi."""

from __future__ import annotations

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	_rename_module()
	_rename_doctype()
	_rename_installed_app()


def _rename_module():
	if frappe.db.exists("Module Def", "OpsPilot"):
		if not frappe.db.exists("Module Def", "OpsAi"):
			rename_doc("Module Def", "OpsPilot", "OpsAi", force=True, show_alert=False)
		else:
			# Model sync may already have created OpsAi; drop the orphan.
			frappe.delete_doc("Module Def", "OpsPilot", force=True, ignore_permissions=True)

	if frappe.db.exists("Module Def", "OpsAi"):
		frappe.db.set_value("Module Def", "OpsAi", "app_name", "opsai", update_modified=False)


def _rename_doctype():
	if frappe.db.exists("DocType", "OpsPilot Settings") and not frappe.db.exists(
		"DocType", "OpsAi Settings"
	):
		rename_doc("DocType", "OpsPilot Settings", "OpsAi Settings", force=True, show_alert=False)

	if frappe.db.exists("DocType", "OpsAi Settings"):
		frappe.db.set_value("DocType", "OpsAi Settings", "module", "OpsAi", update_modified=False)


def _rename_installed_app():
	if frappe.db.exists("Installed Application", {"app_name": "opspilot_frappe"}):
		frappe.db.set_value(
			"Installed Application",
			{"app_name": "opspilot_frappe"},
			"app_name",
			"opsai",
			update_modified=False,
		)

	installed = frappe.get_installed_apps()
	if "opspilot_frappe" in installed:
		installed = ["opsai" if app == "opspilot_frappe" else app for app in installed]
		frappe.db.set_global("installed_apps", frappe.as_json(installed))
