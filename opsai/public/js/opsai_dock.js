// OpsAi utility icon in the left dock / sidebar — same tray as Search, Notifications, Flow.
// Uses the OpsAi logo asset (not Lucide) so dock matches chat + apps branding.
//
// Two different OpsAi entries on Desk:
//   • Dock app tile (top) → OpsAi workspace via app_home /desk/opsai (hooks.py)
//   • This utility icon   → toggles the chat side panel (like Flow)
(() => {
	function can_use_opsai() {
		return Boolean(frappe.boot?.has_opsai_access);
	}

	function ensure_launcher() {
		$(document).trigger("opsai:ensure");
		return window.opsai;
	}

	function toggle_opsai_panel() {
		ensure_launcher();
		if (window.opsai?.toggle) {
			window.opsai.toggle();
			return;
		}
		// Launcher script may not have run yet — retry briefly (same tick / next paints)
		let tries = 0;
		const timer = setInterval(() => {
			tries += 1;
			ensure_launcher();
			if (window.opsai?.toggle) {
				clearInterval(timer);
				window.opsai.toggle();
				return;
			}
			if (tries >= 20) {
				clearInterval(timer);
				frappe.msgprint({
					title: __("OpsAi"),
					message: __(
						"OpsAi chat is not available. Build the opsai.chat island (bench build --app opsai) and reload."
					),
					indicator: "orange",
				});
			}
		}, 50);
	}

	function opsai_icon_html() {
		// Line-art bot-in-bubble (same mark as opsai-icon.svg); currentColor follows Desk ink
		return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none" class="opsai-dock-icon" width="16" height="16" aria-hidden="true" style="width:16px;height:16px;display:block;color:var(--ink-gray-7,#525252)">
			<path d="M43 15 H57" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>
			<path d="M50 15 V28" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>
			<path d="M34 28 H66 C76 28 82 34 82 44 V60 C82 70 76 76 66 76 H48 L36 90 L40 76 H34 C24 76 18 70 18 60 V44 C18 34 24 28 34 28 Z" stroke="currentColor" stroke-width="5" stroke-linejoin="round" fill="none"/>
			<path d="M18 42 V58" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>
			<path d="M82 42 V58" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>
			<circle cx="40" cy="46" r="4.5" fill="currentColor"/>
			<circle cx="60" cy="46" r="4.5" fill="currentColor"/>
			<path d="M40 58 C45 65 55 65 60 58" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" fill="none"/>
		</svg>`;
	}

	function make_opsai_item() {
		return {
			label: __("OpsAi Chat"),
			icon: "bot",
			standard: true,
			type: "Button",
			class: "sidebar-opsai",
			onClick: toggle_opsai_panel,
		};
	}

	function patch_dock() {
		if (!frappe.ui?.Dock?.prototype || frappe.ui.Dock.prototype.__opsai_patched) return;
		const original = frappe.ui.Dock.prototype.render_utilities;
		frappe.ui.Dock.prototype.render_utilities = function () {
			original.call(this);
			append_dock_opsai(this);
		};
		frappe.ui.Dock.prototype.__opsai_patched = true;
	}

	function append_dock_opsai(dock) {
		if (!can_use_opsai() || !dock?.$dock) return;
		const $utilities = dock.$dock.find(".dock-utilities");
		if (!$utilities.length || $utilities.find(".sidebar-opsai").length) return;
		const $opsai = dock.make_utility({
			label: __("OpsAi Chat"),
			icon: "bot",
			css_class: "sidebar-opsai",
		});
		$opsai.find(".dock-item-icon").html(opsai_icon_html());
		// Capture + stopPropagation so nothing else on Desk handles this click
		$opsai[0].addEventListener(
			"click",
			(event) => {
				event.preventDefault();
				event.stopPropagation();
				toggle_opsai_panel();
			},
			true
		);
		$utilities.append($opsai);
	}

	function patch_sidebar() {
		if (!frappe.ui?.Sidebar?.prototype || frappe.ui.Sidebar.prototype.__opsai_patched) return;
		const original = frappe.ui.Sidebar.prototype.add_standard_items;
		frappe.ui.Sidebar.prototype.add_standard_items = function (...args) {
			original.apply(this, args);
			append_sidebar_opsai(this);
		};
		frappe.ui.Sidebar.prototype.__opsai_patched = true;
	}

	function append_sidebar_opsai(sidebar) {
		if (!can_use_opsai() || !sidebar?.$standard_items_band) return;
		if (sidebar.$standard_items_band.find(".sidebar-opsai").length) return;
		sidebar.add_item(sidebar.$standard_items_band, make_opsai_item());
		const $item = sidebar.$standard_items_band.find(".sidebar-opsai");
		$item.find(".sidebar-item-icon, .icon, svg").first().replaceWith(opsai_icon_html());
		const $icon_slot = $item.find(".item-icon, .standard-sidebar-item .icon").first();
		if ($icon_slot.length) $icon_slot.replaceWith(opsai_icon_html());
		else $item.find("svg").first().replaceWith(opsai_icon_html());
	}

	function ensure_mounted() {
		patch_dock();
		patch_sidebar();
		const sidebar = frappe.app?.sidebar;
		if (!sidebar) return;
		if (sidebar.dock) append_dock_opsai(sidebar.dock);
		append_sidebar_opsai(sidebar);
		// Warm the launcher so the first utility click toggles immediately
		if (can_use_opsai()) ensure_launcher();
	}

	patch_dock();
	patch_sidebar();
	$(document).on("app_ready", ensure_mounted);
	if (window.frappe?.boot) {
		frappe.after_ajax?.(() => ensure_mounted());
		$(ensure_mounted);
	}
})();
