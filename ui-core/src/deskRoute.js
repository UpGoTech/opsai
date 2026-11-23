/**
 * Desk paths Hermes (and tool UIs) emit as /app/... or /desk/... links.
 * When OpsAi is docked beside Desk, those should push the host Vue route
 * instead of opening a new tab / full reload. Standalone /opsai keeps _blank.
 */

const DESK_PREFIX = /^\/(app|desk)(\/|$)/

function parseUrl(href, base) {
	if (!href || typeof href !== "string") return null
	const trimmed = href.trim()
	if (!trimmed || trimmed.startsWith("#")) return null
	// mailto:, javascript:, etc. — not Desk
	if (/^\w+:/i.test(trimmed) && !/^https?:/i.test(trimmed)) return null
	try {
		return new URL(trimmed, base)
	} catch {
		return null
	}
}

function sameSite(url, base) {
	let origin
	try {
		origin = new URL(base)
	} catch {
		return false
	}
	if (url.origin === origin.origin) return true
	// Hermes often emits the site URL without the browser's port (or http vs https)
	return url.hostname === origin.hostname && DESK_PREFIX.test(url.pathname)
}

/**
 * Hermes sometimes JSON-encodes filter values in the query string, e.g.
 *   customer=%22Takraf%20India%20Private%20Limited%22
 * which is the JSON string `"Takraf…"`. Desk list filters only JSON.parse
 * array values (`[…]`), so the quotes become part of the equals match and
 * the filter misses. Unwrap JSON strings/arrays/objects here.
 */
export function coerceRouteOptionValue(value) {
	if (typeof value !== "string") return value
	const trimmed = value.trim()
	if (!trimmed) return value
	const first = trimmed[0]
	const last = trimmed[trimmed.length - 1]
	if (
		(first === "[" && last === "]") ||
		(first === "{" && last === "}") ||
		(first === '"' && last === '"')
	) {
		try {
			return JSON.parse(trimmed)
		} catch {
			return value
		}
	}
	return value
}

export function deskRouteOptionsFromSearch(search) {
	const options = {}
	if (!search) return options
	const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search)
	for (const [key, value] of params) options[key] = coerceRouteOptionValue(value)
	return options
}

function encodeRouteOptions(options) {
	const params = new URLSearchParams()
	for (const [key, value] of Object.entries(options)) {
		params.set(
			key,
			value !== null && typeof value === "object" ? JSON.stringify(value) : String(value)
		)
	}
	return params.toString()
}

/** Same-site Desk pathname (+ search/hash), or null. Search left as emitted. */
export function deskPathFromHref(href, base = globalThis.location?.href) {
	const url = parseUrl(href, base)
	if (!url || !sameSite(url, base)) return null
	if (!DESK_PREFIX.test(url.pathname)) return null
	return `${url.pathname}${url.search}${url.hash}`
}

/**
 * Desk href with /desk path and query values Desk list filters understand.
 * Returns null when the href is not a same-site Desk link.
 */
export function normalizeDeskHref(href, base = globalThis.location?.href) {
	const url = parseUrl(href, base)
	if (!url || !sameSite(url, base) || !DESK_PREFIX.test(url.pathname)) return null
	const pathname = url.pathname.replace(/^\/app(?=\/|$)/, "/desk")
	const qs = encodeRouteOptions(deskRouteOptionsFromSearch(url.search))
	return `${pathname}${qs ? `?${qs}` : ""}${url.hash}`
}

/**
 * Push a Desk route without leaving the page. Returns true when handled.
 * Mirrors Frappe's body-level <a> handler (route_options, route_hash).
 */
export function navigateDeskHref(href, { base = globalThis.location?.href } = {}) {
	const normalized = normalizeDeskHref(href, base)
	if (!normalized) return false
	const frappe = globalThis.frappe
	const setRoute = frappe?.set_route
	if (typeof setRoute !== "function") return false

	let url
	try {
		url = new URL(normalized, base)
	} catch {
		return false
	}

	const options = deskRouteOptionsFromSearch(url.search)
	if (Object.keys(options).length) frappe.route_options = options
	if (url.hash) frappe.route_hash = url.hash

	setRoute(url.pathname)
	return true
}

/** True when a plain left-click should try Desk navigation (no modifiers). */
export function shouldInterceptDeskClick(event) {
	if (!event || event.defaultPrevented) return false
	if (event.button != null && event.button !== 0) return false
	if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false
	return true
}

/** Find the clicked <a href> even when the target is a text node or nested span. */
export function anchorFromClick(event) {
	const path = typeof event.composedPath === "function" ? event.composedPath() : []
	for (const node of path) {
		if (node?.nodeType === 1 && node.matches?.("a[href]")) return node
	}
	const target = event.target
	if (target?.nodeType === 1) return target.closest?.("a[href]") ?? null
	return target?.parentElement?.closest?.("a[href]") ?? null
}
