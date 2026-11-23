# Copyright (c) 2026, OpsAi and contributors
# For license information, please see license.txt

from __future__ import annotations

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document


def normalize_gateway_url(url: str | None) -> str:
	"""Canonical Hermes base URL for uniqueness (scheme + host + port [+ path])."""
	raw = (url or "").strip().rstrip("/")
	if not raw:
		return ""
	if "://" not in raw:
		raw = f"http://{raw}"
	parsed = urlparse(raw)
	host = (parsed.hostname or "").lower()
	if not host:
		return (url or "").strip().rstrip("/")
	scheme = (parsed.scheme or "http").lower()
	port = parsed.port
	netloc = f"{host}:{port}" if port else host
	path = (parsed.path or "").rstrip("/")
	if path and path != "/":
		return f"{scheme}://{netloc}{path}"
	return f"{scheme}://{netloc}"


class OpsAiUsers(Document):
	def validate(self):
		if not self.user:
			frappe.throw(_("User is required"))

		# Document name is the User id (autoname field:user).
		if self.name and self.name != self.user:
			frappe.throw(_("Document name must match the User"))

		# User assignment is immutable — delete and recreate for another user.
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and previous.user and previous.user != self.user:
				frappe.throw(
					_(
						"User cannot be changed on OpsAi Users. "
						"Delete this record and create settings for the new user."
					)
				)

		if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
			if self.user != frappe.session.user:
				frappe.throw(_("You can only manage your own OpsAi Users"))

		if not (self.gateway_url or "").strip():
			frappe.throw(_("Gateway URL is required"))

		self.gateway_url = normalize_gateway_url(self.gateway_url)
		if not self.gateway_url:
			frappe.throw(_("Gateway URL is required"))

		if not self.auth_mode:
			self.auth_mode = "password"

		self._validate_unique_gateway_url()

	def _validate_unique_gateway_url(self):
		"""Each Hermes agent (host:port) may be linked to only one OpsAi user."""
		key = normalize_gateway_url(self.gateway_url)
		if not key:
			return

		rows = frappe.get_all(
			"OpsAi Users",
			fields=["name", "user", "gateway_url"],
			filters={"name": ["!=", self.name or ""]},
			limit_page_length=500,
		)
		for row in rows:
			other = normalize_gateway_url(row.gateway_url)
			if other and other == key:
				owner = row.user or row.name
				frappe.throw(
					_(
						"Hermes Gateway URL {0} is already assigned to user {1}. "
						"Each Hermes agent (including port) must be unique — "
						"e.g. host:32798 for one user, host:32788 for another."
					).format(key, owner),
					frappe.DuplicateEntryError,
				)

	def before_insert(self):
		# Do not default User — create form requires an explicit choice.
		if not self.auth_mode:
			self.auth_mode = "password"


def get_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"`tabOpsAi Users`.user = {frappe.db.escape(user)}"


def has_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	if not doc:
		return True
	owner_user = getattr(doc, "user", None) or getattr(doc, "name", None)
	return owner_user == user
