"""Chat attachments for OpsAi — stage private Frappe Files, push to Hermes.

Mirrors OpsPilot / Hermes Desktop remote attach:
- images → gateway ``image.attach_bytes``
- other files → gateway ``file.attach`` with a data URL, then ``@file:`` refs
  are appended to the prompt text.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
from typing import Any

import frappe
from frappe import _

# OpsPilot parity (src/lib/attachments.ts).
ATTACH_IMAGE_MAX_BYTES = 25 * 1024 * 1024
ATTACH_FILE_MAX_BYTES = 80 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10

IMAGE_EXT = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp"})
FILE_EXT = frozenset(
	{
		"pdf",
		"xls",
		"xlsx",
		"xlsm",
		"csv",
		"doc",
		"docx",
		"txt",
		"md",
		"rtf",
		"html",
		"htm",
		"zip",
		"rar",
		"7z",
	}
)
SUPPORTED_EXT = IMAGE_EXT | FILE_EXT

MIME_BY_EXT = {
	"png": "image/png",
	"jpg": "image/jpeg",
	"jpeg": "image/jpeg",
	"gif": "image/gif",
	"webp": "image/webp",
	"bmp": "image/bmp",
	"pdf": "application/pdf",
	"xls": "application/vnd.ms-excel",
	"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	"xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
	"csv": "text/csv",
	"doc": "application/msword",
	"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	"txt": "text/plain",
	"md": "text/markdown",
	"rtf": "application/rtf",
	"html": "text/html",
	"htm": "text/html",
	"zip": "application/zip",
	"rar": "application/vnd.rar",
	"7z": "application/x-7z-compressed",
}

CACHE_PREFIX = "opsai_attachment"
CACHE_TTL = 3600


def extension_of(name: str) -> str:
	base = os.path.basename(name or "")
	dot = base.rfind(".")
	return base[dot + 1 :].lower() if dot >= 0 else ""


def classify_attachment(name: str, mime: str | None = None) -> str | None:
	"""Return ``image`` | ``file`` | None (unsupported). Extension wins over MIME."""
	ext = extension_of(name)
	if ext in FILE_EXT:
		return "file"
	if ext in IMAGE_EXT:
		return "image"
	if mime and re.match(r"^image/(png|jpe?g|gif|webp|bmp)$", mime, re.I):
		return "image"
	return None


def mime_for(name: str, mime: str | None = None) -> str:
	if mime and mime != "application/octet-stream":
		return mime
	return MIME_BY_EXT.get(extension_of(name)) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def max_bytes_for(kind: str) -> int:
	return ATTACH_IMAGE_MAX_BYTES if kind == "image" else ATTACH_FILE_MAX_BYTES


def _cache_key(file: str) -> str:
	return f"{CACHE_PREFIX}:{frappe.session.user}:{file}"


def _parse_attachment_ids(attachments: list | str | None) -> list[str]:
	if attachments is None:
		return []
	if isinstance(attachments, str):
		try:
			import json

			attachments = json.loads(attachments or "[]")
		except (TypeError, ValueError):
			attachments = [attachments] if attachments.strip() else []
	if not isinstance(attachments, list):
		return []
	out: list[str] = []
	seen: set[str] = set()
	for item in attachments:
		name = ""
		if isinstance(item, str):
			name = item.strip()
		elif isinstance(item, dict):
			name = str(item.get("id") or item.get("file") or item.get("name") or "").strip()
		if not name or name in seen:
			continue
		seen.add(name)
		out.append(name)
	return out


def _readable_owned_file(file: str):
	if not file or not frappe.db.exists("File", file):
		frappe.throw(_("File not found: {0}").format(file), frappe.DoesNotExistError)
	doc = frappe.get_doc("File", file)
	if not frappe.has_permission("File", "read", doc=doc):
		frappe.throw(_("Not permitted to use this file."), frappe.PermissionError)
	if doc.owner != frappe.session.user:
		frappe.throw(_("You can only attach files you uploaded."), frappe.PermissionError)
	return doc


def stage_attachment(file: str, model: str | None = None) -> dict[str, Any]:
	"""Validate an uploaded private File for chat use (OpsPilot / Flow chip metadata).

	``model`` is accepted for client parity; Hermes reads files itself so we do not OCR.
	"""
	_ = model  # reserved for future vision/OCR decisions
	file = (file or "").strip()
	if not file:
		frappe.throw(_("File is required."), title=_("Invalid Attachment"))

	doc = _readable_owned_file(file)
	fname = doc.file_name or os.path.basename((doc.file_url or "").split("?")[0]) or file
	kind = classify_attachment(fname, mimetypes.guess_type(fname)[0])
	if not kind:
		frappe.throw(
			_("Unsupported file type. Supported: images, PDF, Excel, Word, HTML, ZIP, RAR."),
			title=_("Unsupported File"),
		)

	size = int(doc.file_size or 0)
	if size <= 0:
		try:
			size = len(doc.get_content() or b"")
		except Exception:
			size = 0
	limit = max_bytes_for(kind)
	if size > limit:
		mb = limit // (1024 * 1024)
		frappe.throw(
			_("{0} is too large (max {1} MB).").format(fname, mb),
			title=_("File Too Large"),
		)

	# Keep chat uploads private under Home/OpsAi when possible.
	try:
		from opsai.artifacts import ensure_opsai_folder

		ensure_opsai_folder()
		if not doc.is_private:
			doc.is_private = 1
			doc.save(ignore_permissions=True)
		if (doc.folder or "") != "Home/OpsAi" and not doc.attached_to_doctype:
			doc.folder = "Home/OpsAi"
			doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="OpsAi attachment folder move failed")

	meta = {
		"file": doc.name,
		"file_name": fname,
		"file_size": size,
		"kind": kind,
	}
	frappe.cache().set_value(_cache_key(doc.name), meta, expires_in_sec=CACHE_TTL)
	return {"file": doc.name, "file_name": fname, "file_size": size}


def cleanup_attachments(
	attachments: list | str | None = None,
	session: str | None = None,
) -> dict[str, list[str]]:
	"""Discard staged uploads the user owns that are not linked to a DocType."""
	_ = session  # OpsAi sessions are Hermes-backed; cleanup is by File ownership.
	removed: list[str] = []
	for file in _parse_attachment_ids(attachments):
		row = frappe.db.get_value(
			"File", file, ["owner", "attached_to_doctype", "is_folder"], as_dict=True
		)
		if not row or row.is_folder:
			continue
		if row.owner != frappe.session.user or row.attached_to_doctype:
			continue
		try:
			frappe.delete_doc("File", file, ignore_permissions=True)
			removed.append(file)
			frappe.cache().delete_value(_cache_key(file))
		except Exception:
			frappe.log_error(title=f"OpsAi attachment cleanup failed: {file}")
	return {"removed": removed}


def load_attachment_bytes(file: str) -> dict[str, Any]:
	"""Load an owned File as bytes + Hermes attach metadata."""
	doc = _readable_owned_file(file)
	fname = doc.file_name or os.path.basename((doc.file_url or "").split("?")[0]) or file
	kind = classify_attachment(fname)
	if not kind:
		frappe.throw(_("Unsupported file type: {0}").format(fname), title=_("Unsupported File"))
	content = doc.get_content()
	if not content:
		frappe.throw(_("{0} is empty.").format(fname), title=_("Empty File"))
	limit = max_bytes_for(kind)
	if len(content) > limit:
		mb = limit // (1024 * 1024)
		frappe.throw(_("{0} is too large (max {1} MB).").format(fname, mb), title=_("File Too Large"))
	mime = mime_for(fname)
	b64 = base64.b64encode(content).decode("ascii")
	return {
		"file": doc.name,
		"file_name": fname,
		"file_size": len(content),
		"kind": kind,
		"mime": mime,
		"content_base64": b64,
		"data_url": f"data:{mime};base64,{b64}",
	}


def partition_attachment_ids(attachments: list | str | None) -> tuple[list[dict], list[dict]]:
	"""Load File ids → (images, files) payloads for Hermes gateway attach."""
	ids = _parse_attachment_ids(attachments)
	if len(ids) > MAX_ATTACHMENTS_PER_MESSAGE:
		frappe.throw(
			_("Attach at most {0} files per message.").format(MAX_ATTACHMENTS_PER_MESSAGE),
			title=_("Too Many Files"),
		)
	images: list[dict[str, Any]] = []
	files: list[dict[str, Any]] = []
	for fid in ids:
		row = load_attachment_bytes(fid)
		if row["kind"] == "image":
			images.append(row)
		else:
			files.append(row)
	return images, files


def default_caption(images: list, files: list) -> str:
	"""OpsPilot / Desktop: attachment-only turns still need a short caption."""
	if images and not files:
		return _("What do you see in this image?")
	return _("Please review the attached file(s).")


def caption_for_attachment_ids(attachments: list | str | None) -> str:
	"""Pick the OpsPilot default caption without reading file bytes."""
	has_image = False
	has_file = False
	for fid in _parse_attachment_ids(attachments):
		try:
			doc = _readable_owned_file(fid)
		except Exception:
			continue
		kind = classify_attachment(doc.file_name or fid)
		if kind == "image":
			has_image = True
		elif kind == "file":
			has_file = True
	return default_caption(
		[{"kind": "image"}] if has_image else [],
		[{"kind": "file"}] if has_file else [],
	)


def user_message_blocks(message: str, attachments: list | str | None) -> list[dict[str, Any]]:
	"""Build Flow-compatible user_message content (text + attachment chips)."""
	blocks: list[dict[str, Any]] = [{"type": "text", "text": message or ""}]
	for fid in _parse_attachment_ids(attachments):
		try:
			doc = _readable_owned_file(fid)
		except Exception:
			continue
		fname = doc.file_name or fid
		kind = classify_attachment(fname) or "file"
		blocks.append({"type": "attachment", "id": fid, "name": fname, "kind": kind})
	return blocks
