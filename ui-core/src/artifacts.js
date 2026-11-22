/** Hermes / Frappe file artifacts — Desktop `::preview` parity. */

const SERVER_ROOT = String.raw`\/(?:opt|home|tmp|var|Users|root|data)`
/** Broader than the Preview/Download card set — every /opt/… path is scrubbed from prose. */
const SCRUB_EXT = String.raw`pdf|zip|rar|7z|xls|xlsx|xlsm|csv|doc|docx|ppt|pptx|txt|md|rtf|png|jpe?g|gif|webp|bmp|html?|xhtml|json|xml|yaml|yml|py|js|ts|sh|log`
const ARTIFACT_EXT = String.raw`html?|xhtml|pdf`
const PATH_CORE = String.raw`${SERVER_ROOT}\/[^\s)\]>"'\`]+?\.(?:${SCRUB_EXT})`
const ARTIFACT_PATH_CORE = String.raw`${SERVER_ROOT}\/[^\s)\]>"'\`]+?\.(?:${ARTIFACT_EXT})`
const FRAPPE_FILE = String.raw`\/(?:private\/)?files\/[^\s)\]>"'\`]+?\.(?:${ARTIFACT_EXT})`

const PREVIEW_RE = new RegExp(
	String.raw`(?<=^|\s)::preview\{([^{}]{0,2048})\}`,
	"gi",
)

function pathAnywhereRe() {
	return new RegExp(
		String.raw`(?:sandbox:|file:\/\/|MEDIA:)?\`?(${PATH_CORE})\`?`,
		"gi",
	)
}

function mdLinkToPathRe() {
	return new RegExp(
		String.raw`\[[^\]]*\]\((?:sandbox:|file:\/\/|MEDIA:)?\`?(${PATH_CORE})\`?\)`,
		"gi",
	)
}

function leadInPhraseRe() {
	return new RegExp(
		String.raw`(?:^|[\n.!?])\s*(?:Created(?:\s+and\s+verified)?(?:\s+the)?(?:\s+\w+\s+file)?|The verified (?:\w+\s+)?download is available|Here(?:'s| is)(?:\s+the)?(?:\s+\w+)?|Also saved as a file(?:\s*\([^)]*\))?|File\s*path|Saved\s*(?:to|as)|Download(?:\s+the)?(?:\s+\w+)?(?:\s+here)?(?:\s+at)?|You can (?:download|find) (?:it|the file)(?:\s+at|here)?)\s*[:：]?\s*`,
		"gi",
	)
}

const ARTIFACT_PATH_RE = new RegExp(
	String.raw`(?:sandbox:|file:\/\/|MEDIA:)?\`?(${ARTIFACT_PATH_CORE}|${FRAPPE_FILE})\`?`,
	"gi",
)

const ARTIFACT_MD_LINK_RE = new RegExp(
	String.raw`\[[^\]]*\]\((?:sandbox:|file:\/\/|MEDIA:)?\`?(${ARTIFACT_PATH_CORE}|${FRAPPE_FILE})\`?\)`,
	"gi",
)

export function filenameOf(path) {
	const clean = String(path || "").split("?")[0]
	return clean.split(/[/\\]/).pop() || "download"
}

export function extOf(path) {
	const name = filenameOf(path)
	const dot = name.lastIndexOf(".")
	return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ""
}

export function isHtmlExt(ext) {
	return ext === "html" || ext === "htm" || ext === "xhtml"
}

export function isPdfExt(ext) {
	return ext === "pdf"
}

export function isArtifactExt(ext) {
	return isHtmlExt(ext) || isPdfExt(ext)
}

/** Parse `file="…"` (or unquoted) from a directive body. */
export function fileAttr(body) {
	const m = /(?:^|[\s,;])file\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s,}]+))/i.exec(body || "")
	return (m?.[1] || m?.[2] || m?.[3] || "").trim() || null
}

/**
 * Split assistant text into prose / ::preview segments (Desktop transcript directives).
 * Unclaimed / malformed directives stay as prose.
 */
export function segmentTranscriptDirectives(source) {
	const raw = source || ""
	const re = new RegExp(String.raw`(?:^|\s)(::preview\{([^{}]{0,2048})\})`, "gi")
	const segments = []
	let last = 0
	let m
	while ((m = re.exec(raw))) {
		const full = m[1]
		const body = m[2] || ""
		const at = m.index + m[0].indexOf("::")
		if (at > last) segments.push({ kind: "prose", text: raw.slice(last, at) })
		segments.push({
			kind: "directive",
			name: "preview",
			attrs: { file: fileAttr(body) || "" },
			source: full,
		})
		last = at + full.length
	}
	if (last < raw.length) segments.push({ kind: "prose", text: raw.slice(last) })
	return segments.length ? segments : [{ kind: "prose", text: raw }]
}

function pushUnique(out, path) {
	const cleaned = String(path || "")
		.replace(/[.,;:]+$/, "")
		.trim()
	if (!cleaned || !isArtifactExt(extOf(cleaned))) return
	if (out.some((a) => a.path === cleaned || a.file_url === cleaned)) return
	const ext = extOf(cleaned)
	const isFrappe = cleaned.startsWith("/private/files/") || cleaned.startsWith("/files/")
	out.push({
		path: isFrappe ? null : cleaned,
		file_url: isFrappe ? cleaned : null,
		filename: filenameOf(cleaned),
		ext,
	})
}

/** Collect HTML/PDF paths (Hermes workspace or Frappe private URLs). */
export function extractArtifacts(source, extras = []) {
	const raw = [source || "", ...extras.filter(Boolean)].join("\n")
	const out = []

	PREVIEW_RE.lastIndex = 0
	let m
	while ((m = PREVIEW_RE.exec(raw))) {
		const file = fileAttr(m[1])
		if (file) pushUnique(out, file)
	}
	ARTIFACT_MD_LINK_RE.lastIndex = 0
	while ((m = ARTIFACT_MD_LINK_RE.exec(raw))) pushUnique(out, m[1])
	ARTIFACT_PATH_RE.lastIndex = 0
	while ((m = ARTIFACT_PATH_RE.exec(raw))) pushUnique(out, m[1])

	return out
}

/** Hide gateway paths in chat prose — cards / ::preview own the file UI. */
export function scrubArtifactPaths(source) {
	if (!source) return source
	let next = source
	next = next.replace(mdLinkToPathRe(), "")
	next = next.replace(pathAnywhereRe(), "")
	next = next.replace(PREVIEW_RE, "")
	next = next.replace(leadInPhraseRe(), (match) => {
		const lead = match[0]
		if (lead === "." || lead === "!" || lead === "?") return `${lead}\n`
		return "\n"
	})
	next = next.replace(/\bDownload the PDF\b/gi, "")
	next = next.replace(/(?:^|\n)[ \t]*[:：][ \t]*(?=\n|$)/g, "\n")
	return next.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim()
}

export function labelForExt(ext) {
	if (isHtmlExt(ext)) return "HTML"
	if (isPdfExt(ext)) return "PDF"
	return (ext || "FILE").toUpperCase()
}

/** Authenticated Preview URL (inline) for a private Frappe file. */
export function previewUrlFor(fileUrl, fid = null) {
	if (!fileUrl && !fid) return null
	const params = new URLSearchParams()
	if (fileUrl) params.set("file_url", fileUrl)
	if (fid) params.set("fid", fid)
	return `/api/method/opsai.api.artifact_file?${params.toString()}`
}

/** Authenticated Download URL (attachment) for a private Frappe file. */
export function downloadUrlFor(fileUrl, fid = null) {
	const base = previewUrlFor(fileUrl, fid)
	if (!base) return null
	return `${base}&download=1`
}
