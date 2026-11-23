# Copyright (c) 2026, OpsAi and contributors
# License: MIT. See LICENSE

"""Hermes gateway WebSocket JSON-RPC — same protocol as Hermes Desktop remote.

The dashboard URL (e.g. :32798) does not expose OpenAI `/v1/chat/completions` to the
network (api_server binds 127.0.0.1:8642). Chat goes over `/api/ws` after minting a
one-shot ticket from `/api/auth/ws-ticket`.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request

import frappe
from frappe import _

from opsai.hermes import (
	HermesError,
	_auth_headers,
	_base_url,
	_error_detail,
	_opener,
	ensure_session,
	get_user_settings,
)

try:
	import websocket
except ImportError:  # pragma: no cover
	websocket = None  # type: ignore


# Terminal event types that end a prompt turn.
_TURN_DONE = frozenset(
	{
		"message.complete",
		"error",
		"run.failed",
		"run.cancelled",
		"agent.error",
	}
)


def _require_ws():
	if websocket is None:
		raise HermesError(
			_("Missing dependency websocket-client. Run: bench pip install websocket-client")
		)


def _ws_url(settings: dict[str, Any], *, ticket: str | None = None, token: str | None = None) -> str:
	parsed = urlparse(_base_url(settings).rstrip("/") + "/")
	scheme = "wss" if parsed.scheme == "https" else "ws"
	prefix = parsed.path.rstrip("/")
	if prefix == "/":
		prefix = ""
	netloc = parsed.netloc
	if ticket:
		return f"{scheme}://{netloc}{prefix}/api/ws?ticket={quote(ticket, safe='')}"
	if token:
		return f"{scheme}://{netloc}{prefix}/api/ws?token={quote(token, safe='')}"
	raise HermesError(_("Hermes WebSocket URL requires a ticket or session token."))


def mint_ws_ticket(settings: dict[str, Any] | None = None) -> str:
	"""POST /api/auth/ws-ticket — single-use, ~30s."""
	settings = ensure_session(settings or get_user_settings())
	headers = _auth_headers(settings)
	if "Cookie" not in headers and "Authorization" not in headers:
		raise HermesError(_("Not connected to Hermes. Open OpsAi Users and click Connect."))

	# Prefer cookie jar for ticket mint (password mode).
	url = urljoin(_base_url(settings), "api/auth/ws-ticket")
	req = Request(
		url,
		data=b"{}",
		headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with _opener().open(req, timeout=20) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			code = getattr(resp, "status", 200)
			if code >= 400:
				raise HermesError(_("WS ticket mint failed ({0}): {1}").format(code, _error_detail(raw)))
			body = json.loads(raw) if raw else {}
			ticket = (body or {}).get("ticket") if isinstance(body, dict) else None
			if not ticket:
				raise HermesError(_("WS ticket mint returned no ticket."))
			return str(ticket)
	except HermesError:
		raise
	except HTTPError as err:
		raw = err.read().decode("utf-8", errors="replace") if err.fp else str(err)
		if err.code in (401, 403):
			raise HermesError(_("Hermes session expired — open OpsAi Users and click Connect.")) from err
		raise HermesError(_("WS ticket mint failed ({0}): {1}").format(err.code, _error_detail(raw)[:400])) from err
	except URLError as err:
		raise HermesError(_("Could not reach Hermes: {0}").format(err.reason or err)) from err
	except (TypeError, ValueError) as err:
		raise HermesError(_("Invalid WS ticket response: {0}").format(err)) from err


def resolve_ws_url(settings: dict[str, Any] | None = None) -> str:
	"""Cookie sessions → remint ticket; token sessions → ?token=."""
	settings = ensure_session(settings or get_user_settings())
	auth_mode = (settings.get("auth_mode") or "password").strip()
	token = (settings.get("session_token") or "").strip()
	cookies = settings.get("session_cookies") or {}

	if auth_mode in ("token", "session_token") and token and not cookies:
		return _ws_url(settings, token=token)

	if cookies or auth_mode == "password":
		ticket = mint_ws_ticket(settings)
		return _ws_url(settings, ticket=ticket)

	if token:
		return _ws_url(settings, token=token)

	raise HermesError(_("Not connected to Hermes. Open OpsAi Users and click Connect."))


class GatewayClient:
	"""One-shot WebSocket JSON-RPC client for a single OpsAi request."""

	def __init__(self, settings: dict[str, Any] | None = None, *, timeout: float = 30):
		_require_ws()
		self.settings = ensure_session(settings or get_user_settings())
		self.timeout = timeout
		self._ws = None
		self._next_id = 0
		self._buffer = ""

	def __enter__(self) -> GatewayClient:
		self.connect()
		return self

	def __exit__(self, *exc) -> None:
		self.close()

	def connect(self):
		url = resolve_ws_url(self.settings)
		self._ws = websocket.create_connection(
			url,
			timeout=self.timeout,
		)
		# Drain gateway.ready (and anything else) briefly so the first RPC is clean.
		self._ws.settimeout(2)
		try:
			while True:
				self._recv_raw()
		except Exception:
			pass
		self._ws.settimeout(self.timeout)

	def close(self):
		if self._ws is not None:
			try:
				self._ws.close()
			except Exception:
				pass
			self._ws = None

	def _recv_raw(self) -> dict[str, Any]:
		assert self._ws is not None
		while True:
			chunk = self._ws.recv()
			if isinstance(chunk, bytes):
				chunk = chunk.decode("utf-8", errors="replace")
			self._buffer += chunk
			# Prefer newline-delimited frames; also accept a lone JSON object.
			while True:
				if "\n" in self._buffer:
					line, self._buffer = self._buffer.split("\n", 1)
					line = line.strip()
					if not line:
						continue
					return json.loads(line)
				trimmed = self._buffer.strip()
				if trimmed.startswith("{") and trimmed.endswith("}"):
					try:
						obj = json.loads(trimmed)
					except (TypeError, ValueError):
						break
					self._buffer = ""
					return obj
				break

	def rpc(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> Any:
		assert self._ws is not None
		self._next_id += 1
		rid = f"r{self._next_id}"
		frame = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
		# Hermes gateway expects a trailing newline.
		self._ws.send(json.dumps(frame) + "\n")
		self._ws.settimeout(timeout if timeout is not None else self.timeout)
		events: list[dict] = []
		deadline = time.time() + (timeout if timeout is not None else self.timeout)
		while time.time() < deadline:
			remaining = max(0.1, deadline - time.time())
			self._ws.settimeout(remaining)
			try:
				msg = self._recv_raw()
			except Exception as err:
				raise HermesError(_("Hermes gateway RPC timed out: {0}").format(method)) from err
			if msg.get("id") == rid:
				if msg.get("error"):
					err = msg["error"]
					detail = err.get("message") if isinstance(err, dict) else str(err)
					raise HermesError(_("Hermes RPC {0}: {1}").format(method, detail))
				return msg.get("result")
			events.append(msg)
		raise HermesError(_("Hermes gateway RPC timed out: {0}").format(method))

	def rpc_flexible(self, method: str, params: dict, *, timeout: float | None = None) -> Any:
		"""Call RPC; on 'Extra inputs are not permitted' strip offending keys and retry."""
		try:
			return self.rpc(method, params, timeout=timeout)
		except HermesError as err:
			msg = str(err)
			if "Extra inputs are not permitted" not in msg and "invalid params" not in msg.lower():
				raise
			stripped = dict(params)
			changed = False
			for key in list(stripped):
				if f"{key}:" in msg or f'"{key}"' in msg or f"'{key}'" in msg:
					stripped.pop(key, None)
					changed = True
			return self.rpc(method, stripped if changed else {}, timeout=timeout)

	def prompt_turn(
		self,
		*,
		session_id: str,
		text: str,
		timeout: float = 300,
		on_event=None,
	) -> str:
		"""prompt.submit + collect until message.complete.

		`on_event(etype, payload)` is called for each gateway event so the UI can
		mirror Desktop (thinking / text deltas / tools) while the turn runs.
		"""
		assert self._ws is not None
		params = {"session_id": session_id, "text": text}
		try:
			self.rpc_flexible("prompt.submit", params, timeout=30)
		except HermesError:
			raise

		assembled: list[str] = []
		final = ""
		deadline = time.time() + timeout
		while time.time() < deadline:
			remaining = max(0.5, deadline - time.time())
			self._ws.settimeout(remaining)
			try:
				msg = self._recv_raw()
			except Exception as err:
				if final or assembled:
					break
				raise HermesError(_("Hermes chat timed out waiting for a reply.")) from err

			if msg.get("method") != "event":
				continue
			event = msg.get("params") or {}
			etype = event.get("type") or ""
			payload = event.get("payload")
			if not isinstance(payload, dict):
				payload = {}

			if on_event:
				try:
					on_event(etype, payload)
				except Exception:
					pass

			if etype in ("message.delta", "message.interim"):
				piece = payload.get("text") or payload.get("delta") or payload.get("content") or ""
				if piece:
					assembled.append(str(piece))
			elif etype == "message.complete":
				text_out = payload.get("text") or payload.get("content")
				if isinstance(text_out, str) and text_out.strip():
					final = text_out
				else:
					final = "".join(assembled)
				return final.strip()
			elif etype == "error":
				raise HermesError(
					_("Hermes error: {0}").format(
						payload.get("message") or payload.get("error") or "gateway error"
					)
				)
			elif etype in _TURN_DONE - {"message.complete", "error"}:
				return (final or "".join(assembled)).strip()

		return (final or "".join(assembled)).strip()


def create_gateway_session(
	*,
	title: str | None = None,
	approval_mode: str | None = None,
	settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""session.create via WS — returns stored + live ids."""
	params: dict[str, Any] = {"source": "gui"}
	if title:
		params["title"] = title
	if approval_mode == "Auto-approve":
		params["yolo"] = True

	with GatewayClient(settings, timeout=30) as gw:
		try:
			result = gw.rpc_flexible("session.create", params, timeout=60)
		except HermesError:
			# Last resort: empty params (strict schemas).
			result = gw.rpc("session.create", {}, timeout=60)

	if not isinstance(result, dict):
		raise HermesError(_("session.create returned an unexpected payload."))

	live = str(result.get("session_id") or result.get("id") or "")
	stored = str(result.get("stored_session_id") or live)
	if not stored:
		raise HermesError(_("session.create returned no session id."))

	info = result.get("info") if isinstance(result.get("info"), dict) else {}
	return {
		"id": stored,
		"session_id": live or stored,
		"stored_session_id": stored,
		"live_id": live or stored,
		"title": title or result.get("title") or "Chat",
		"model": (info or {}).get("model") or result.get("model"),
		"yolo": bool(result.get("yolo") or (info or {}).get("yolo")),
		"source": "gui",
	}


def resume_gateway_session(
	stored_session_id: str,
	*,
	settings: dict[str, Any] | None = None,
) -> str:
	"""session.resume / session.activate → live session_id for prompt.submit."""
	with GatewayClient(settings, timeout=30) as gw:
		try:
			result = gw.rpc("session.resume", {"session_id": stored_session_id}, timeout=60)
		except HermesError as err:
			if "unknown method" in str(err).lower():
				result = gw.rpc("session.activate", {"session_id": stored_session_id}, timeout=60)
			else:
				# Maybe already live under that id.
				if "not found" in str(err).lower() or "4001" in str(err):
					raise
				try:
					result = gw.rpc("session.activate", {"session_id": stored_session_id}, timeout=60)
				except HermesError:
					return stored_session_id

	if isinstance(result, dict):
		live = str(result.get("session_id") or result.get("stored_session_id") or stored_session_id)
		return live or stored_session_id
	return stored_session_id


def _attach_files_to_session(
	gw: GatewayClient,
	session_id: str,
	*,
	images: list[dict[str, Any]] | None = None,
	files: list[dict[str, Any]] | None = None,
) -> list[str]:
	"""OpsPilot parity: image.attach_bytes + file.attach → @file: refs for the prompt."""
	file_refs: list[str] = []
	for img in images or []:
		gw.rpc(
			"image.attach_bytes",
			{
				"session_id": session_id,
				"content_base64": img.get("content_base64") or "",
				"filename": img.get("file_name") or img.get("name") or "image.png",
			},
			timeout=120,
		)
	for row in files or []:
		name = row.get("file_name") or row.get("name") or "file"
		data_url = row.get("data_url") or ""
		if not data_url:
			raise HermesError(_("Could not attach {0}: missing file bytes").format(name))
		result = gw.rpc(
			"file.attach",
			{
				"session_id": session_id,
				"name": name,
				"data_url": data_url,
			},
			timeout=180,
		)
		if not isinstance(result, dict) or not result.get("attached") or not result.get("ref_text"):
			detail = (result or {}).get("message") if isinstance(result, dict) else None
			raise HermesError(detail or _("Could not attach {0}").format(name))
		file_refs.append(str(result["ref_text"]))
	return file_refs


def run_gateway_turn(
	session: str,
	message: str,
	*,
	settings: dict[str, Any] | None = None,
	timeout: float = 300,
	on_event=None,
	images: list[dict[str, Any]] | None = None,
	files: list[dict[str, Any]] | None = None,
) -> str:
	"""Resume (or treat as live) + optional attaches + prompt.submit + wait for complete."""
	message = (message or "").strip()
	has_attachments = bool(images or files)
	if not message and not has_attachments:
		raise HermesError(_("Message is required"))

	with GatewayClient(settings, timeout=30) as gw:
		live = session
		# Prefer resume so durable stored ids become live runtime ids.
		try:
			result = gw.rpc("session.resume", {"session_id": session}, timeout=60)
			if isinstance(result, dict):
				live = str(result.get("session_id") or session)
		except HermesError as err:
			msg = str(err).lower()
			if "unknown method" in msg:
				try:
					result = gw.rpc("session.activate", {"session_id": session}, timeout=60)
					if isinstance(result, dict):
						live = str(result.get("session_id") or session)
				except HermesError:
					live = session
			elif "not found" in msg or "4001" in msg or "4006" in msg:
				# Brand-new local id that Hermes never saw — create then submit.
				created = gw.rpc_flexible("session.create", {"source": "gui"}, timeout=60)
				if isinstance(created, dict):
					live = str(created.get("session_id") or created.get("stored_session_id") or session)
			# else: try submit with the given id

		def _submit(live_id: str) -> str:
			file_refs = _attach_files_to_session(gw, live_id, images=images, files=files)
			final_text = message
			if file_refs:
				final_text = f"{message}\n\n{chr(10).join(file_refs)}" if message else "\n".join(file_refs)
			if not (final_text or "").strip() and has_attachments:
				# Images alone still need a caption for prompt.submit.
				final_text = _("What do you see in this image?") if images and not files else _(
					"Please review the attached file(s)."
				)
			return gw.prompt_turn(
				session_id=live_id, text=final_text, timeout=timeout, on_event=on_event
			)

		try:
			return _submit(live)
		except HermesError as err:
			if "session not found" not in str(err).lower() and "4001" not in str(err):
				raise
			# One more create+submit cycle.
			created = gw.rpc_flexible("session.create", {"source": "gui"}, timeout=60)
			if not isinstance(created, dict):
				raise
			live = str(created.get("session_id") or created.get("stored_session_id") or "")
			if not live:
				raise
			return _submit(live)
