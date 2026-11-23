<template>
	<!-- Empty state until Hermes is configured, or while the brain is disconnected. -->
	<div
		class="flex w-full flex-1 flex-col items-center gap-8 self-stretch justify-center pb-10"
	>
		<div class="flex flex-col items-center gap-4 text-center">
			<div
				v-if="brainMissing"
				class="grid size-14 place-items-center rounded-full bg-surface-gray-2 text-ink-gray-5"
				aria-hidden="true"
			>
				<span class="lucide-brain size-7 opacity-70" />
			</div>
			<BrandMark v-else line :size="28" />
			<div class="flex flex-col gap-1.5">
				<h1 class="text-2xl-semibold text-ink-gray-9">{{ heading }}</h1>
				<p
					v-if="brainMissing"
					class="max-w-md text-pretty text-base italic text-ink-gray-6"
				>
					“{{ quote }}”
				</p>
				<p class="max-w-sm text-pretty text-p-base text-ink-gray-5">{{ subline }}</p>
			</div>
			<span
				v-if="brainMissing"
				class="inline-flex items-center gap-1.5 rounded-full bg-surface-gray-2 px-3 py-1 text-sm text-ink-gray-6"
			>
				<span class="size-1.5 rounded-full bg-surface-gray-5" aria-hidden="true" />
				{{ __("Brain offline") }}
			</span>
		</div>
		<Button
			v-if="canConfigure && !brainMissing"
			variant="solid"
			:label="__('Open OpsAi Users')"
			@click="openSettings"
		/>
		<Button
			v-else-if="canConfigure && brainMissing"
			variant="solid"
			:label="__('Grant access in OpsAi Users')"
			@click="openSettings"
		/>
	</div>
</template>

<script setup>
import { computed, inject } from "vue";
import { Button } from "frappe-ui";
import BrandMark from "@opsai/ui-core/components/BrandMark.vue";
import { __ } from "@opsai/ui-core/translate.js";

const flow = inject("opsai");
const page = inject("opsaiPage");
const hasModels = computed(() => page.state.boot.models.length > 0);
const canConfigure = computed(() => page.can("OpsAi Users", "write") || page.can("OpsAi Users", "create"));
const brainMissing = computed(
	() => Boolean(page.state.boot.hermes_configured) && page.state.boot.hermes_connected === false
);

const QUOTES = [
	__("A body without a brain can only wait."),
	__("The agent is awake. Its Hermes brain is not."),
	__("Thought needs a connection — this one is missing."),
	__("OpsAi is here. Hermes stepped away."),
	__("No brain on the line — Connect to think again."),
];

const quote = computed(() => QUOTES[new Date().getDate() % QUOTES.length]);

const greeting = computed(() => {
	const hour = new Date().getHours();
	const name = page.state.boot.user?.full_name?.split(" ")[0];
	if (hour < 5) return name ? __("Hello, {0}", [name]) : __("Hello");
	if (hour < 12) return name ? __("Good morning, {0}", [name]) : __("Good morning");
	if (hour < 17) return name ? __("Good afternoon, {0}", [name]) : __("Good afternoon");
	return name ? __("Good evening, {0}", [name]) : __("Good evening");
});

const heading = computed(() => (brainMissing.value ? __("Brain not connected") : greeting.value));

const ACCESS_LINES = [
	__("The brain is behind a locked door — ask an administrator for the key."),
	__("Hermes is offline until someone with clearance wakes it. Ask an administrator."),
	__("Your assistant is ready; its mind is not. Ask an administrator to grant access."),
	__("No signal to the brain yet. Ask an administrator to open the gate."),
	__("Thought is on hold. Ask an administrator to restore Hermes access."),
];

const accessLine = computed(() => ACCESS_LINES[new Date().getDate() % ACCESS_LINES.length]);

const subline = computed(() => {
	if (brainMissing.value) return accessLine.value;
	if (!hasModels.value) {
		return canConfigure.value
			? __("Set your Hermes gateway URL in OpsAi Users to get started.")
			: __("Ask an administrator to configure OpsAi Users.");
	}
	return __("Ask an administrator to enable an agent.");
});

function openSettings() {
	// Connect lives on the Desk OpsAi Users form — open it when Hermes is offline.
	if (brainMissing.value) {
		const user = page.state.boot.user?.name;
		if (window.frappe?.set_route && user) {
			window.frappe.set_route("Form", "OpsAi Users", user);
			return;
		}
		if (user) {
			window.open(`/app/opsai-users/${encodeURIComponent(user)}`, "_blank");
			return;
		}
	}
	page.state.settingsTab = null;
	flow.setSettingsOpen(true);
}
</script>
