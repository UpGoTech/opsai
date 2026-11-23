import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";

const BASE = "https://erp.fabrixcel.com/app/home";
const dom = new JSDOM("<body></body>", { url: BASE });
globalThis.location = dom.window.location;

const {
	anchorFromClick,
	coerceRouteOptionValue,
	deskPathFromHref,
	navigateDeskHref,
	normalizeDeskHref,
	shouldInterceptDeskClick,
} = await import("@opsai/ui-core/deskRoute.js");

test("deskPathFromHref accepts same-origin /app and /desk URLs Hermes emits", () => {
	assert.equal(
		deskPathFromHref("https://erp.fabrixcel.com/app/supplier", BASE),
		"/app/supplier"
	);
	assert.equal(deskPathFromHref("/app/supplier", BASE), "/app/supplier");
	assert.equal(
		deskPathFromHref("https://erp.fabrixcel.com/desk/sales-invoice/INV-1?foo=1#bar", BASE),
		"/desk/sales-invoice/INV-1?foo=1#bar"
	);
	assert.equal(deskPathFromHref("/desk/todo", BASE), "/desk/todo");
});

test("deskPathFromHref accepts same hostname when port or protocol differs", () => {
	assert.equal(
		deskPathFromHref("http://erp.fabrixcel.com/app/supplier", "https://erp.fabrixcel.com:8000/desk"),
		"/app/supplier"
	);
	assert.equal(
		deskPathFromHref("http://fxl.localhost/app/supplier", "http://fxl.localhost:8000/desk/home"),
		"/app/supplier"
	);
});

test("deskPathFromHref rejects external, non-Desk, and special schemes", () => {
	assert.equal(deskPathFromHref("https://other.example/app/supplier", BASE), null);
	assert.equal(deskPathFromHref("https://erp.fabrixcel.com/opsai", BASE), null);
	assert.equal(deskPathFromHref("mailto:a@b.com", BASE), null);
	assert.equal(deskPathFromHref("#section", BASE), null);
	assert.equal(deskPathFromHref("", BASE), null);
});

test("coerceRouteOptionValue unwraps JSON-quoted Hermes filter values", () => {
	assert.equal(coerceRouteOptionValue('"Takraf India Private Limited"'), "Takraf India Private Limited");
	assert.deepEqual(coerceRouteOptionValue('["=","Takraf India Private Limited"]'), [
		"=",
		"Takraf India Private Limited",
	]);
	assert.equal(coerceRouteOptionValue("Takraf India Private Limited"), "Takraf India Private Limited");
	assert.equal(coerceRouteOptionValue("view"), "view");
});

test("normalizeDeskHref strips JSON quotes from list filter query params", () => {
	assert.equal(
		normalizeDeskHref(
			'http://fxl.localhost/app/project?customer=%22Takraf%20India%20Private%20Limited%22',
			"http://fxl.localhost/desk/home"
		),
		"/desk/project?customer=Takraf+India+Private+Limited"
	);
});

test("navigateDeskHref pushes /desk path and unquoted filter via frappe.set_route", () => {
	const routes = [];
	globalThis.frappe = {
		set_route(...args) {
			routes.push(args);
		},
	};
	assert.equal(
		navigateDeskHref(
			'https://erp.fabrixcel.com/app/project?customer=%22Takraf%20India%20Private%20Limited%22#row',
			{ base: BASE }
		),
		true
	);
	assert.deepEqual(routes, [["/desk/project"]]);
	assert.deepEqual(globalThis.frappe.route_options, {
		customer: "Takraf India Private Limited",
	});
	assert.equal(globalThis.frappe.route_hash, "#row");
	assert.equal(navigateDeskHref("https://other.example/app/x", { base: BASE }), false);
	delete globalThis.frappe;
});

test("navigateDeskHref is a no-op without frappe.set_route", () => {
	delete globalThis.frappe;
	assert.equal(navigateDeskHref("/app/supplier", { base: BASE }), false);
});

test("shouldInterceptDeskClick ignores modified and non-primary clicks", () => {
	assert.equal(shouldInterceptDeskClick({ button: 0 }), true);
	assert.equal(shouldInterceptDeskClick({ button: 1 }), false);
	assert.equal(shouldInterceptDeskClick({ button: 0, metaKey: true }), false);
	assert.equal(shouldInterceptDeskClick({ button: 0, ctrlKey: true }), false);
	assert.equal(shouldInterceptDeskClick({ button: 0, defaultPrevented: true }), false);
});

test("anchorFromClick finds the link via composedPath", () => {
	const doc = dom.window.document;
	const a = doc.createElement("a");
	a.href = "/app/supplier";
	const span = doc.createElement("span");
	a.append(span);
	assert.equal(anchorFromClick({ composedPath: () => [span, a, doc.body], target: span }), a);
	const orphan = doc.createElement("span");
	assert.equal(anchorFromClick({ composedPath: () => [orphan], target: orphan }), null);
});
