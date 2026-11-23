"""Move Password-field Auth rows from OpsAi Settings → OpsAi Users.

`rename_doc("DocType", …)` does not rewrite `__Auth.doctype`, so Connect could
no longer decrypt gateway_password / session_cookies after the DocType rename.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "OpsAi Users"):
		return

	# Prefer keeping a row already keyed as OpsAi Users when both exist.
	frappe.db.sql(
		"""
		delete from `__Auth`
		where doctype = %s
		  and exists (
			select 1 from `__Auth` a2
			where a2.doctype = %s
			  and a2.name = `__Auth`.name
			  and a2.fieldname = `__Auth`.fieldname
		  )
		""",
		("OpsAi Settings", "OpsAi Users"),
	)
	frappe.db.sql(
		"update `__Auth` set doctype = %s where doctype = %s",
		("OpsAi Users", "OpsAi Settings"),
	)
