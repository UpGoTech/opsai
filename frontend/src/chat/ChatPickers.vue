<template>
	<!-- Agent icon + Hermes connection status; skills stay beside it on a new chat. -->
	<span class="relative flex min-w-0 flex-none items-center gap-1.5">
		<Tooltip :text="open === 'agent' ? '' : __('Agent: {0}', [agentTitle])">
			<button
				ref="agentButton"
				type="button"
				:class="[BUTTON, tall ? 'h-8 w-8' : 'h-7 w-7', open === 'agent' && 'bg-surface-gray-2']"
				:aria-label="__('Agent: {0}', [agentTitle])"
				:aria-expanded="open === 'agent'"
				@click="toggle('agent')"
			>
				<span class="lucide-bot size-4" aria-hidden="true" />
			</button>
		</Tooltip>
		<span
			class="inline-flex items-center gap-1.5 whitespace-nowrap text-sm"
			:class="connected ? 'text-ink-green-3' : 'text-ink-gray-5'"
			:title="statusTitle"
		>
			<span
				class="size-1.5 flex-none rounded-full"
				:class="connected ? 'bg-green-500' : 'bg-surface-gray-5'"
				aria-hidden="true"
			/>
			{{ connected ? __("Connected") : __("Disconnected") }}
		</span>
		<AgentPicker v-if="open === 'agent'" @close="close" />
	</span>
	<span v-if="hasSkills && starting" class="relative flex-none">
		<Tooltip :text="open === 'skills' ? '' : __('Skills')">
			<button
				ref="skillsButton"
				type="button"
				:class="[BUTTON, tall ? 'h-8 w-8' : 'h-7 w-7', open === 'skills' && 'bg-surface-gray-2']"
				:aria-label="__('Skills')"
				:aria-expanded="open === 'skills'"
				@click="toggle('skills')"
			>
				<span class="lucide-book-open size-4" aria-hidden="true" />
			</button>
		</Tooltip>
		<SkillPicker v-if="open === 'skills'" @close="close" @pick="pick" />
	</span>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, ref } from "vue";
import { Tooltip } from "frappe-ui";
import { __ } from "@opsai/ui-core/translate.js";

import { call } from "../api/frappe.js";
import { useAgent } from "./agent.js";
import AgentPicker from "./AgentPicker.vue";
import SkillPicker from "./SkillPicker.vue";

const props = defineProps({
	insert: { type: Function, required: true },
	tall: { type: Boolean, default: false },
	starting: { type: Boolean, default: true },
});
const flow = inject("opsai");
const page = inject("opsaiPage");
const { current } = useAgent();

const open = ref(null); // "agent" | "skills"
const agentButton = ref(null);
const skillsButton = ref(null);
const connected = ref(
	page.state.boot.hermes_connected !== undefined
		? Boolean(page.state.boot.hermes_connected)
		: Boolean(page.state.boot.hermes_configured)
);
const statusMessage = ref("");
const agentTitle = computed(
	() => page.state.boot.agents.find((agent) => agent.name === current.value)?.title ?? __("Agent")
);
const statusTitle = computed(
	() =>
		statusMessage.value ||
		(connected.value ? __("Hermes brain is online") : __("Hermes brain is offline — Connect in OpsAi Users"))
);
const hasSkills = computed(() => (flow.state.skills ?? []).length > 0 || page.can("Flow Skill", "create"));

async function refreshStatus() {
	try {
		const result = await call("opsai.api.test_connection");
		connected.value = Boolean(result?.connected);
		statusMessage.value = result?.message || "";
		page.state.boot.hermes_connected = connected.value;
	} catch (err) {
		connected.value = false;
		statusMessage.value = err?.message || __("Connection failed");
		page.state.boot.hermes_connected = false;
	}
}

onMounted(() => {
	void refreshStatus();
});

function toggle(name) {
	open.value = open.value === name ? null : name;
}

function close(refocus = true) {
	const button = open.value === "agent" ? agentButton : skillsButton;
	open.value = null;
	if (refocus !== false) nextTick(() => button.value?.focus());
}

function pick(word) {
	close(false);
	props.insert(word);
}

const BUTTON =
	"grid flex-none place-items-center rounded-5 text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9 dark:text-ink-gray-8";
</script>
