# Copyright (c) 2026, OpsAi and contributors
# License: MIT. See LICENSE

"""HTTP client for the user's Hermes gateway (dashboard login + OpenAI / sessions API)."""

from __future__ import annotations

import json
import re
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import (
	HTTPCookieProcessor,
	HTTPErrorProcessor,
	HTTPSHandler,
	OpenerDirector,
	Request,
	build_opener,
)

import frappe
from frappe import _


class HermesError(Exception):
	"""Raised for Hermes HTTP/auth failures — not a Frappe ValidationError (avoids msgprint dialogs)."""

	pass


class _NoRedirect(HTTPErrorProcessor):
	"""Do not follow 3xx — Hermes sends 302 → /login when the session is missing/expired."""

	def http_response(self, request, response):
		return response

	https_response = http_response


def _opener(cookiejar: CookieJar | None = None) -> OpenerDirector:
	handlers: list = [_NoRedirect(), HTTPSHandler()]
	if cookiejar is not None:
		handlers.insert(0, HTTPCookieProcessor(cookiejar))
	return build_opener(*handlers)


def get_user_settings(user: str | None = None) -> dict[str, Any]:
	"""Load the signed-in user's OpsAi Users (Password fields decrypted)."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Not logged in"), frappe.AuthenticationError)

	if not frappe.db.exists("OpsAi Users", user):
		frappe.throw(
			_("Set your OpsAi Users (Gateway URL) before using Hermes."),
			frappe.ValidationError,
		)

	doc = frappe.get_doc("OpsAi Users", user)
	if doc.user != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	cookies_raw = doc.get_password("session_cookies", raise_exception=False) or ""
	cookies = {}
	if cookies_raw:
		try:
			parsed = json.loads(cookies_raw)
			if isinstance(parsed, dict):
				cookies = {str(k): str(v) for k, v in parsed.items()}
		except (TypeError, ValueError):
			cookies = {}

	return {
		"name": doc.name,
		"user": doc.user,
		"gateway_url": doc.gateway_url or "",
		"auth_mode": doc.auth_mode or "password",
		"gateway_username": doc.gateway_username or "",
		"gateway_password": doc.get_password("gateway_password", raise_exception=False) or "",
		"session_token": doc.get_password("session_token", raise_exception=False) or "",
		"session_cookies": cookies,
		"connection_status": (doc.connection_status or "").strip(),
		"default_provider": getattr(doc, "default_provider", None) or "",
		"default_model": getattr(doc, "default_model", None) or "",
	}


def is_explicitly_disconnected(settings: dict[str, Any] | None) -> bool:
	"""True only when OpsAi Users was marked Disconnected (sticky until Connect)."""
	if not settings:
		return False
	status = (settings.get("connection_status") or "").strip().lower()
	# Avoid substring traps: "disconnected" contains "connected".
	return status == "disconnected" or status.startswith("disconnected ")


def session_reconnect_allowed(settings: dict[str, Any] | None) -> bool:
	"""Auto password_login / token use only when the user has not clicked Disconnect."""
	return not is_explicitly_disconnected(settings)


def is_hermes_connected(settings: dict[str, Any] | None) -> bool:
	"""Live Hermes session available for chat (not merely gateway URL configured)."""
	if not settings or not (settings.get("gateway_url") or "").strip():
		return False
	if is_explicitly_disconnected(settings):
		return False
	status = (settings.get("connection_status") or "").strip().lower()
	if status == "connected" or status.startswith("connected "):
		return True
	# Legacy rows without connection_status: cookies or token imply a session.
	auth_mode = (settings.get("auth_mode") or "password").strip()
	if auth_mode in ("token", "session_token") and (settings.get("session_token") or "").strip():
		return True
	return bool(settings.get("session_cookies"))


def _save_session_cookies(user: str, cookies: dict[str, str]):
	"""Persist Hermes dashboard session cookies on OpsAi Users."""
	if not user or not frappe.db.exists("OpsAi Users", user):
		return
	doc = frappe.get_doc("OpsAi Users", user)
	doc.session_cookies = json.dumps(cookies)
	doc.connection_status = _("Connected")
	# Empty Password fields on a loaded doc would otherwise be wiped by _save_passwords.
	doc.flags.ignore_save_passwords = ["gateway_password", "session_token"]
	doc.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit — connect must persist before next call


def _cookie_header(cookies: dict[str, str]) -> str:
	return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def _auth_headers(settings: dict[str, Any]) -> dict[str, str]:
	headers = {
		"Content-Type": "application/json",
		"Accept": "application/json",
	}
	# Explicit Disconnect must stick — do not send cookies or Bearer until Connect.
	if is_explicitly_disconnected(settings):
		return headers
	auth_mode = (settings.get("auth_mode") or "password").strip()
	token = (settings.get("session_token") or "").strip()
	cookies = settings.get("session_cookies") or {}

	if auth_mode in ("token", "session_token") and token:
		headers["Authorization"] = f"Bearer {token}"
	elif cookies:
		headers["Cookie"] = _cookie_header(cookies)
	elif token:
		# Legacy: treat stored token as Bearer if present.
		headers["Authorization"] = f"Bearer {token}"
	return headers


def _base_url(settings: dict[str, Any]) -> str:
	return settings["gateway_url"].rstrip("/") + "/"


def _parse_set_cookie(headers) -> dict[str, str]:
	"""Extract name=value pairs from Set-Cookie headers (incl. __Host- / __Secure-)."""
	out: dict[str, str] = {}
	# urllib may expose get_all on email.message.Message
	raw_list = []
	if hasattr(headers, "get_all"):
		raw_list = headers.get_all("Set-Cookie") or headers.get_all("set-cookie") or []
	elif hasattr(headers, "getlist"):
		raw_list = headers.getlist("Set-Cookie") or []
	else:
		one = headers.get("Set-Cookie") or headers.get("set-cookie")
		if one:
			raw_list = [one]

	for raw in raw_list:
		part = (raw or "").split(";", 1)[0].strip()
		if "=" not in part:
			continue
		name, value = part.split("=", 1)
		name = name.strip()
		# Normalize prefixed cookie names Hermes may use
		for prefix in ("__Host-", "__Secure-"):
			if name.startswith(prefix):
				name = name[len(prefix) :]
		if name:
			out[name] = value.strip()
	return out


def _discover_password_provider(settings: dict[str, Any], jar: CookieJar) -> str:
	"""Read data-provider from /login (defaults to basic)."""
	login_url = urljoin(_base_url(settings), "login")
	req = Request(
		login_url,
		headers={
			"Accept": "text/html,application/xhtml+xml",
			"User-Agent": "OpsAi-HermesClient/1.0",
		},
		method="GET",
	)
	try:
		with _opener(jar).open(req, timeout=15) as resp:
			html = resp.read().decode("utf-8", errors="replace")
	except Exception:
		return "basic"
	match = re.search(r'data-provider=["\']([^"\']+)["\']', html)
	return match.group(1) if match else "basic"


def password_login(settings: dict[str, Any], *, persist: bool = True) -> dict[str, str]:
	"""POST /auth/password-login (same as Hermes Sign in) and return session cookies."""
	# Do not strip password — only trim username; passwords may be intentionally spaced.
	username = (settings.get("gateway_username") or "").strip()
	password = settings.get("gateway_password") or ""
	if isinstance(password, str):
		# Strip a single trailing newline that some password managers insert; keep internal spaces.
		password = password.removesuffix("\n").removesuffix("\r")
	if not username or not password:
		raise HermesError(_("Gateway Username and Password are required to connect."))

	base = _base_url(settings)
	jar = CookieJar()
	provider = _discover_password_provider(settings, jar)

	url = urljoin(base, "auth/password-login")
	payload = {
		"provider": provider,
		"username": username,
		"password": password,
		"next": "/",
	}
	body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	req = Request(
		url,
		data=body,
		headers={
			"Content-Type": "application/json",
			"Accept": "application/json",
			"Origin": base.rstrip("/"),
			"Referer": urljoin(base, "login"),
			"User-Agent": "OpsAi-HermesClient/1.0",
		},
		method="POST",
	)
	try:
		with _opener(jar).open(req, timeout=30) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			code = getattr(resp, "status", 200)
			cookies = _parse_set_cookie(resp.headers)
			for c in jar:
				name = c.name
				for prefix in ("__Host-", "__Secure-"):
					if name.startswith(prefix):
						name = name[len(prefix) :]
				cookies[name] = c.value
			if code >= 400:
				raise HermesError(_("Hermes login failed ({0}): {1}").format(code, _error_detail(raw)))
			keep = {
				k: v
				for k, v in cookies.items()
				if "hermes_session" in k or k in ("hermes_session_at", "hermes_session_rt")
			}
			cookies = keep or cookies
			if not cookies:
				raise HermesError(_("Hermes login succeeded but returned no session cookies."))
			if persist and settings.get("user"):
				_save_session_cookies(settings["user"], cookies)
			settings["session_cookies"] = cookies
			return cookies
	except HermesError:
		raise
	except HTTPError as err:
		raw = err.read().decode("utf-8", errors="replace") if err.fp else str(err)
		# 401 from Hermes password provider
		raise HermesError(
			_("Hermes login failed ({0}): {1}").format(err.code, _error_detail(raw)[:400])
		) from err
	except URLError as err:
		raise HermesError(_("Could not reach Hermes: {0}").format(err.reason or err)) from err


def ensure_session(settings: dict[str, Any]) -> dict[str, Any]:
	"""Ensure password-mode settings carry a live cookie jar (login if needed).

	Never auto-login after an explicit Disconnect — Connect in OpsAi Users must run first.
	"""
	if is_explicitly_disconnected(settings):
		raise HermesError(_("Hermes is disconnected. Open OpsAi Users and click Connect."))
	auth_mode = (settings.get("auth_mode") or "password").strip()
	if auth_mode in ("token", "session_token") and settings.get("session_token"):
		return settings
	if settings.get("session_cookies"):
		return settings
	if (
		session_reconnect_allowed(settings)
		and (settings.get("gateway_username") or "").strip()
		and (settings.get("gateway_password") or "").strip()
	):
		password_login(settings, persist=True)
	return settings


def _error_detail(raw: str) -> str:
	if not raw:
		return raw
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		if "Sign in" in raw or "<!doctype html>" in raw.lower():
			return "Hermes login page (session expired — reconnect)"
		return raw[:400]
	if not isinstance(parsed, dict):
		return raw
	err = parsed.get("error")
	if isinstance(err, dict):
		return err.get("message") or err.get("detail") or raw
	if isinstance(err, str):
		detail = parsed.get("detail") or err
		reason = parsed.get("reason")
		return f"{detail} ({reason})" if reason else str(detail)
	return parsed.get("detail") or raw


def is_login_redirect(code: int | None, headers, body: str | None = None) -> bool:
	if code in (301, 302, 303, 307, 308):
		location = ""
		try:
			location = headers.get("Location") or headers.get("location") or ""
		except Exception:
			location = ""
		if "/login" in location:
			return True
	if body and ("Sign in — Hermes" in body or '"login_url"' in (body or "")):
		return True
	return False


def _parse_json_response(code: int, headers, raw: str) -> Any:
	ctype = ""
	try:
		ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
	except Exception:
		pass
	if is_login_redirect(code, headers, raw):
		raise HermesError(_("Hermes session expired — open OpsAi Users and click Connect."))
	if code >= 400:
		raise HermesError(_("Hermes error ({0}): {1}").format(code, _error_detail(raw)[:800]))
	if not raw:
		return None
	if "application/json" not in ctype and raw.lstrip()[:1] not in ("{", "["):
		raise HermesError(
			_("Hermes returned a non-JSON response (HTTP {0}). Reconnect from OpsAi Users.").format(code)
		)
	try:
		return json.loads(raw)
	except (TypeError, ValueError):
		raise HermesError(_("Hermes returned invalid JSON (HTTP {0})").format(code))


def request(
	method: str,
	path: str,
	*,
	body: dict | list | None = None,
	params: dict | None = None,
	timeout: int = 180,
	settings: dict | None = None,
	_retried: bool = False,
) -> Any:
	"""Call Hermes. Auto-reconnects once on login redirect when username/password are set."""
	settings = ensure_session(settings or get_user_settings())
	url = urljoin(_base_url(settings), path.lstrip("/"))
	if params:
		url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"

	headers = _auth_headers(settings)
	if "Authorization" not in headers and "Cookie" not in headers:
		frappe.throw(
			_("Not connected to Hermes. Open OpsAi Users, enter username/password, and click Connect."),
			frappe.ValidationError,
		)
	headers["X-Hermes-Session-Key"] = session_key()

	data = None if body is None else json.dumps(body).encode()
	req = Request(url, data=data, headers=headers, method=method.upper())
	try:
		with _opener().open(req, timeout=timeout) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			code = getattr(resp, "status", 200)
			if is_login_redirect(code, resp.headers, raw) and not _retried:
				# Session expired — refresh cookies and retry once (never after Disconnect).
				if session_reconnect_allowed(settings) and (settings.get("gateway_username") or "").strip():
					password_login(settings, persist=True)
					return request(
						method,
						path,
						body=body,
						params=params,
						timeout=timeout,
						settings=settings,
						_retried=True,
					)
			return _parse_json_response(code, resp.headers, raw)
	except HermesError as err:
		frappe.throw(str(err))
	except HTTPError as err:
		raw = err.read().decode("utf-8", errors="replace") if err.fp else str(err)
		if is_login_redirect(err.code, err.headers, raw) and not _retried:
			if session_reconnect_allowed(settings) and (settings.get("gateway_username") or "").strip():
				password_login(settings, persist=True)
				return request(
					method,
					path,
					body=body,
					params=params,
					timeout=timeout,
					settings=settings,
					_retried=True,
				)
		frappe.throw(_("Hermes error ({0}): {1}").format(err.code, _error_detail(raw)[:800]))
	except URLError as err:
		frappe.throw(_("Could not reach Hermes: {0}").format(err.reason or err))


def try_request(
	method: str,
	path: str,
	*,
	body: dict | list | None = None,
	params: dict | None = None,
	timeout: int = 30,
	settings: dict | None = None,
) -> tuple[bool, Any, str | None]:
	"""HTTP call that never raises — used to probe /api vs /v1 without failing the request."""
	try:
		settings = ensure_session(settings or get_user_settings())
	except Exception as err:
		return False, None, str(err)

	url = urljoin(_base_url(settings), path.lstrip("/"))
	if params:
		url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"

	headers = _auth_headers(settings)
	if "Authorization" not in headers and "Cookie" not in headers:
		return False, None, _("Not connected — click Connect in OpsAi Users")
	headers["X-Hermes-Session-Key"] = session_key()

	data = None if body is None else json.dumps(body).encode()
	req = Request(url, data=data, headers=headers, method=method.upper())
	try:
		with _opener().open(req, timeout=timeout) as resp:
			raw = resp.read().decode("utf-8", errors="replace")
			code = getattr(resp, "status", 200)
			if is_login_redirect(code, resp.headers, raw) or code >= 400:
				# One reconnect attempt for probes (never after Disconnect).
				if session_reconnect_allowed(settings) and (settings.get("gateway_username") or "").strip():
					try:
						password_login(settings, persist=True)
						headers = _auth_headers(settings)
						headers["X-Hermes-Session-Key"] = session_key()
						req2 = Request(url, data=data, headers=headers, method=method.upper())
						with _opener().open(req2, timeout=timeout) as resp2:
							raw2 = resp2.read().decode("utf-8", errors="replace")
							code2 = getattr(resp2, "status", 200)
							if is_login_redirect(code2, resp2.headers, raw2) or code2 >= 400:
								return False, None, _error_detail(raw2) or f"HTTP {code2}"
							if not raw2:
								return True, None, None
							return True, json.loads(raw2), None
					except Exception as err:
						return False, None, str(err)
				return False, None, _error_detail(raw) or f"HTTP {code}"
			ctype = (resp.headers.get("Content-Type") or "").lower()
			if raw and "application/json" not in ctype and raw.lstrip()[:1] not in ("{", "["):
				return False, None, _("Non-JSON response (often the Hermes login page)")
			if not raw:
				return True, None, None
			try:
				return True, json.loads(raw), None
			except (TypeError, ValueError):
				return False, None, _("Invalid JSON from Hermes")
	except HTTPError as err:
		raw = err.read().decode("utf-8", errors="replace") if err.fp else str(err)
		return False, None, _error_detail(raw) or str(err)
	except URLError as err:
		return False, None, str(err.reason or err)
	except Exception as err:
		return False, None, str(err)


def session_key() -> str:
	return f"opsai:{frappe.local.site}:{frappe.session.user}"


def request_bytes(
	method: str,
	path: str,
	*,
	params: dict | None = None,
	timeout: int = 120,
	settings: dict | None = None,
	_retried: bool = False,
) -> bytes:
	"""Authenticated Hermes GET/POST that returns raw bytes (file downloads)."""
	settings = ensure_session(settings or get_user_settings())
	url = urljoin(_base_url(settings), path.lstrip("/"))
	if params:
		url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"

	headers = _auth_headers(settings)
	if "Authorization" not in headers and "Cookie" not in headers:
		raise HermesError(_("Not connected to Hermes. Open OpsAi Users and click Connect."))
	headers["X-Hermes-Session-Key"] = session_key()

	req = Request(url, data=None, headers=headers, method=method.upper())
	try:
		with _opener().open(req, timeout=timeout) as resp:
			raw = resp.read()
			code = getattr(resp, "status", 200)
			# Peek at a text decode only for login / error detection.
			sample = raw[:2000].decode("utf-8", errors="replace") if raw else ""
			if is_login_redirect(code, resp.headers, sample) and not _retried:
				if session_reconnect_allowed(settings) and (settings.get("gateway_username") or "").strip():
					password_login(settings, persist=True)
					return request_bytes(
						method,
						path,
						params=params,
						timeout=timeout,
						settings=settings,
						_retried=True,
					)
				raise HermesError(_("Hermes session expired — reconnect from OpsAi Users."))
			if code >= 400:
				raise HermesError(_("Hermes error ({0}): {1}").format(code, _error_detail(sample)[:800]))
			return raw or b""
	except HermesError:
		raise
	except HTTPError as err:
		raw = err.read() if err.fp else b""
		sample = raw.decode("utf-8", errors="replace") if raw else str(err)
		if is_login_redirect(err.code, err.headers, sample) and not _retried:
			if session_reconnect_allowed(settings) and (settings.get("gateway_username") or "").strip():
				password_login(settings, persist=True)
				return request_bytes(
					method,
					path,
					params=params,
					timeout=timeout,
					settings=settings,
					_retried=True,
				)
		raise HermesError(_("Hermes error ({0}): {1}").format(err.code, _error_detail(sample)[:800])) from err
	except URLError as err:
		raise HermesError(_("Could not reach Hermes: {0}").format(err.reason or err)) from err
