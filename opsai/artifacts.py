"""Ingest Hermes-generated HTML/PDF files into the user's private Frappe files.

Detect workspace paths and ``::preview{file=…}``, pull bytes from the gateway,
rewrite chat text to Frappe private URLs (Hermes Desktop parity).
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.core.doctype.file.utils import make_home_folder
from frappe.utils.file_manager import save_file

from opsai.hermes import HermesError, ensure_session, get_user_settings, request_bytes, try_request

# Absolute workspace roots Hermes commonly writes into.
_SERVER_ROOT = r"/(?:opt|home|tmp|var|Users|root|data)"
_ARTIFACT_EXT = r"html?|xhtml|pdf"
# Allow spaces inside the path (e.g. /opt/data/Open Projects.pdf) but not newlines
# or closing delimiters. Non-greedy up to the artifact extension.
_PATH_CORE = rf"{_SERVER_ROOT}/[^\n)\]>\"'`]+?\.(?:{_ARTIFACT_EXT})\b"

# Leading whitespace is consumed so we don't need a variable-width lookbehind.
_PREVIEW_RE = re.compile(
	rf"(?:^|\s)::preview\{{([^{{}}]{{0,2048}})\}}",
	re.IGNORECASE | re.MULTILINE,
)
_PATH_ANYWHERE_RE = re.compile(
	rf"(?:sandbox:|file://|MEDIA:)?`?({_PATH_CORE})`?",
	re.IGNORECASE,
)
_MD_LINK_RE = re.compile(
	rf"\[[^\]]*\]\((?:sandbox:|file://|MEDIA:)?`?({_PATH_CORE})`?\)",
	re.IGNORECASE,
)
_ATTR_FILE_RE = re.compile(
	r"""(?:^|[\s,;])file\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s,}]+))""",
	re.IGNORECASE,
)

FOLDER = "Home/OpsAi"


def _filename_of(path: str) -> str:
	return os.path.basename(path.rstrip("/")) or "download"


def _ext_of(path: str) -> str:
	name = _filename_of(path)
	dot = name.rfind(".")
	return name[dot + 1 :].lower() if dot >= 0 else ""


def _gateway_path(raw: str) -> str | None:
	"""Resolve Hermes chat hrefs / bare paths to an absolute gateway path."""
	text = (raw or "").strip()
	if not text:
		return None
	if re.match(r"^sandbox:", text, re.I):
		rest = re.sub(r"^sandbox:", "", text, flags=re.I)
		return rest if rest.startswith("/") else f"/{rest}"
	if re.match(r"^file://", text, re.I):
		rest = re.sub(r"^file://", "", text, flags=re.I)
		# file:///opt/... → /opt/...
		if rest.startswith("/") and not rest.startswith("//"):
			return unquote(rest)
		if rest.startswith("//"):
			# file://host/path — drop host
			parts = rest[2:].split("/", 1)
			return unquote("/" + parts[1]) if len(parts) > 1 else None
		return unquote(rest if rest.startswith("/") else f"/{rest}")
	if re.match(r"^MEDIA:", text, re.I):
		rest = re.sub(r"^MEDIA:", "", text, flags=re.I).strip()
		return rest if rest.startswith("/") else f"/{rest}"
	if re.match(rf"^{_SERVER_ROOT}/", text):
		# Keep spaces in filenames (e.g. Open Projects.pdf); only cut at newline.
		line = text.split("\n", 1)[0].strip().rstrip(".,;:)")
		return line or None
	return None


def _file_attr(body: str) -> str | None:
	m = _ATTR_FILE_RE.search(body or "")
	if not m:
		return None
	return (m.group(1) or m.group(2) or m.group(3) or "").strip() or None


def extract_artifact_paths(text: str) -> list[str]:
	"""Unique absolute Hermes paths to HTML/PDF mentioned in assistant text."""
	raw = text or ""
	out: list[str] = []
	seen: set[str] = set()

	def push(candidate: str | None):
		if not candidate:
			return
		path = _gateway_path(candidate) or (
			candidate if candidate.startswith("/") and re.search(rf"\.(?:{_ARTIFACT_EXT})$", candidate, re.I) else None
		)
		if not path:
			return
		path = path.rstrip(".,;:)")
		ext = _ext_of(path)
		if ext not in ("html", "htm", "xhtml", "pdf"):
			return
		if path in seen:
			return
		seen.add(path)
		out.append(path)

	for m in _PREVIEW_RE.finditer(raw):
		push(_file_attr(m.group(1)))
	for m in _MD_LINK_RE.finditer(raw):
		push(m.group(1))
	for m in _PATH_ANYWHERE_RE.finditer(raw):
		push(m.group(1))

	return out


def ensure_opsai_folder() -> str:
	"""Private Home/OpsAi folder for the signed-in user."""
	if not frappe.db.exists("File", {"is_folder": 1, "name": "Home"}):
		make_home_folder()
	if not frappe.db.exists("File", {"is_folder": 1, "name": FOLDER}):
		create_new_folder("OpsAi", "Home")
	return FOLDER


def _fetch_hermes_bytes(path: str, *, settings: dict | None = None) -> bytes:
	"""Download a workspace file from Hermes (/api/fs/download, then fallbacks)."""
	settings = ensure_session(settings or get_user_settings())
	params = {"path": path}
	# Primary Desktop download route.
	try:
		return request_bytes("GET", "/api/fs/download", params=params, timeout=120, settings=settings)
	except HermesError:
		pass
	# Older / alternate routes.
	for alt in ("/api/files/download", "/api/fs/read"):
		try:
			data = request_bytes("GET", alt, params=params, timeout=120, settings=settings)
			if data:
				return data
		except HermesError:
			continue
	# Text probe (HTML / small files sometimes only on read-text).
	ok, payload, err = try_request(
		"GET",
		"/api/fs/read-text",
		params=params,
		timeout=60,
		settings=settings,
	)
	if ok and isinstance(payload, dict) and isinstance(payload.get("text"), str):
		return payload["text"].encode("utf-8")
	if ok and isinstance(payload, str):
		return payload.encode("utf-8")
	raise HermesError(err or _("Could not download {0} from Hermes").format(path))


def save_private_artifact(path: str, content: bytes, *, session: str | None = None) -> dict[str, Any]:
	"""Write bytes into the user's private Home/OpsAi folder."""
	ensure_opsai_folder()
	fname = _filename_of(path)
	# Prefix with a short session tag to avoid silent overwrites across chats.
	if session:
		safe_session = re.sub(r"[^\w.-]+", "_", session)[:24]
		stem, ext = os.path.splitext(fname)
		fname = f"{stem}_{safe_session}{ext}" if stem else fname

	file_doc = save_file(
		fname,
		content,
		None,
		None,
		folder=FOLDER,
		is_private=1,
	)
	# save_file uses ignore_permissions; pin owner to the signed-in user so
	# /private/files/* permission checks (owner == session.user) succeed.
	owner = frappe.session.user
	if file_doc.owner != owner and owner and owner != "Guest":
		file_doc.db_set("owner", owner, update_modified=False)
	return {
		"hermes_path": path,
		"filename": file_doc.file_name or fname,
		"file_url": file_doc.file_url,
		"file_name": file_doc.name,
		"fid": file_doc.name,
		"is_private": 1,
		"ext": _ext_of(file_doc.file_name or fname),
	}


def import_hermes_path(path: str, *, session: str | None = None, settings: dict | None = None) -> dict[str, Any]:
	"""Fetch one Hermes path and store it as a private File."""
	resolved = _gateway_path(path) or path
	if not resolved.startswith("/"):
		frappe.throw(_("Invalid Hermes file path"))
	content = _fetch_hermes_bytes(resolved, settings=settings)
	if not content:
		frappe.throw(_("Hermes returned an empty file for {0}").format(resolved))
	return save_private_artifact(resolved, content, session=session)


def rewrite_artifact_text(text: str, mapping: dict[str, str]) -> str:
	"""Replace Hermes paths with Frappe private file URLs (including ::preview)."""
	if not text or not mapping:
		return text or ""

	# Longest path first so nested names rewrite correctly.
	ordered = sorted(mapping.keys(), key=len, reverse=True)

	def replace_path(src: str) -> str:
		next_text = src
		for hermes_path in ordered:
			next_text = next_text.replace(hermes_path, mapping[hermes_path])
		return next_text

	def rewrite_preview(match: re.Match) -> str:
		full = match.group(0)
		body = match.group(1)
		file_path = _file_attr(body)
		if not file_path:
			return full
		resolved = _gateway_path(file_path) or file_path
		file_url = mapping.get(resolved)
		if not file_url:
			return full
		# Preserve other attrs; swap file= to the Frappe URL.
		new_body = re.sub(
			r"""file\s*=\s*(?:"[^"]*"|'[^']*'|[^\s,}]+)""",
			f'file="{file_url}"',
			body,
			count=1,
			flags=re.IGNORECASE,
		)
		# Keep any leading whitespace captured by (?:^|\s).
		prefix = full[: full.index("::")]
		return f"{prefix}::preview{{{new_body}}}"

	out = _PREVIEW_RE.sub(rewrite_preview, text)
	out = replace_path(out)
	return out


def ingest_assistant_artifacts(session: str, text: str, *, settings: dict | None = None) -> dict[str, Any]:
	"""Download HTML/PDF artifacts, save privately, rewrite message text.

	Returns ``{text, artifacts}`` where artifacts are Frappe file descriptors.
	"""
	paths = extract_artifact_paths(text)
	if not paths:
		return {"text": text or "", "artifacts": []}

	artifacts: list[dict[str, Any]] = []
	mapping: dict[str, str] = {}
	for path in paths:
		try:
			row = import_hermes_path(path, session=session, settings=settings)
			artifacts.append(row)
			mapping[path] = row["file_url"]
		except Exception:
			frappe.log_error(title=f"OpsAi artifact import failed: {path}")
			continue

	return {
		"text": rewrite_artifact_text(text or "", mapping),
		"artifacts": artifacts,
	}
