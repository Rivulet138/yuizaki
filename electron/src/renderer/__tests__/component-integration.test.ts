import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import CompanionPanel from "../domains/companion/views/CompanionPanel.vue";
import MemoryPanel from "../domains/memory/views/MemoryPanel.vue";
import TasksPanel from "../domains/system/views/TasksPanel.vue";

const systemClientMocks = vi.hoisted(() => ({
	companionRuntime: vi.fn(),
	orchestration: vi.fn(),
	setModelSelection: vi.fn(),
	updateCompanionIdleProfile: vi.fn(),
	saveSettings: vi.fn(),
}));

const memoryClientMocks = vi.hoisted(() => ({
	getIndexStatus: vi.fn(),
	removeDoc: vi.fn(),
	removeDocs: vi.fn(),
	previewMaintenance: vi.fn(),
	applyMaintenance: vi.fn(),
}));

const messageBoxMocks = vi.hoisted(() => ({
	confirm: vi.fn(),
}));

vi.mock("@/api/client", () => ({
	systemClient: {
		companionRuntime: systemClientMocks.companionRuntime,
		orchestration: systemClientMocks.orchestration,
	},
	petControlClient: {
		setModelSelection: systemClientMocks.setModelSelection,
		updateCompanionIdleProfile: systemClientMocks.updateCompanionIdleProfile,
	},
	settingsClient: {
		save: systemClientMocks.saveSettings,
	},
}));

vi.mock("@/api/clients/memory-client", () => ({
	memoryClient: {
		getIndexStatus: memoryClientMocks.getIndexStatus,
		removeDoc: memoryClientMocks.removeDoc,
		removeDocs: memoryClientMocks.removeDocs,
		previewMaintenance: memoryClientMocks.previewMaintenance,
		applyMaintenance: memoryClientMocks.applyMaintenance,
	},
}));

vi.mock("@/stores/companionStore", () => ({
	useCompanionStore: () => ({
		activeCompanionId: "comp-1",
		activeCompanion: {
			id: "comp-1",
			name: "Yui",
			model_type: "live2d",
			model_id: "yuizaki-live2d",
			temperament: "playful",
			attachment_style: "attached",
			support_style: "gentle",
			affinity_state: 0.8,
			energy_state: 0.7,
			emotion_state: "warm",
		},
		companions: [{ id: "comp-1", name: "Yui", model_type: "live2d" }],
		loadCompanions: vi.fn().mockResolvedValue(undefined),
		setActiveCompanion: vi.fn(),
		updateCompanion: vi.fn().mockResolvedValue(undefined),
		deleteCompanion: vi.fn().mockResolvedValue(undefined),
	}),
}));

const schedules = ref([
	{
		id: "task-1",
		name: "Drink water",
		prompt: "remind",
		mode: "interval",
		enabled: true,
		owner_agent_role: "router",
		owner_agent_id: "yuizaki.task-router",
		route_reason: "Scheduled interval task owned by task-router",
	},
]);
const schedulesRequest = ref({ loading: false, error: "" });

vi.mock("../domains/system/composables/useSystemDomain", () => ({
	useSystemDomain: () => ({
		schedules,
		schedulesRequest,
		loadSchedules: vi.fn().mockResolvedValue(undefined),
		createOnceSchedule: vi.fn().mockResolvedValue(undefined),
		createIntervalSchedule: vi.fn().mockResolvedValue(undefined),
		removeSchedule: vi.fn().mockResolvedValue(undefined),
		toggleSchedule: vi.fn().mockResolvedValue(undefined),
		runScheduleNow: vi.fn().mockResolvedValue(undefined),
	}),
}));

const docs = ref<any[]>([]);
const queryResult = ref({
	query: "remember preference",
	results: [{ id: "doc-1", score: 0.9, text: "remembered preference" }],
	trace: {
		query: "remember preference",
		scope: "workspace",
		workspace_id: "ws-1",
		session_id: "session-1",
		layers: ["relationship", "working", "profile"],
		recall_count: 1,
		selected_ids: ["doc-1"],
		candidate_limit: 24,
		candidate_count: 3,
		filtered_count: 1,
		filtered_out_count: 2,
		filter_reasons: { workspace: 2 },
		top_score: 0.9,
		average_score: 0.9,
		latency_ms: 12.4,
		backend_filter_downpushed: true,
	},
});

vi.mock("../domains/memory/composables/useMemoryDomain", () => ({
	normalizeDuplicateCandidates: (value: unknown) => Array.isArray(value) ? value : [],
	useMemoryDomain: () => ({
		docs,
		queryResult,
		docsRequest: ref({ loading: false, error: "" }),
		addRequest: ref({ loading: false, error: "" }),
		updateRequest: ref({ loading: false, error: "" }),
		queryRequest: ref({ loading: false, error: "" }),
		rawQueryRequest: ref({ loading: false, error: "" }),
		loadDocs: vi.fn().mockResolvedValue(undefined),
		addMemory: vi.fn().mockResolvedValue({ status: "ok" }),
		updateDoc: vi.fn().mockResolvedValue({ status: "updated" }),
		queryMemory: vi.fn().mockResolvedValue(undefined),
		queryRawRag: vi.fn().mockResolvedValue(undefined),
	}),
}));

vi.mock("@/stores/sessionStore", () => ({
	useSessionStore: () => ({
		activeSession: { id: "session-1" },
	}),
}));

vi.mock("@/stores/workspaceStore", async (importOriginal) => {
	const actual =
		await importOriginal<typeof import("../stores/workspaceStore")>();
	return {
		...actual,
		useWorkspaceStore: () => ({
			activeWorkspace: {
				id: "ws-1",
				name: "Focus",
				memory_scope: "workspace",
				context: {
					activeTab: "companion",
					modelType: "live2d",
					modelId: null,
					wallpaperMode: true,
					heroHeight: 460,
					menuOrder: [],
					recentTabs: ["companion"],
					layoutPreset: "balanced",
					promptMode: "auto",
					promptEngineering: {
						workPrompt: "任务模式",
						dailyPrompt: "日常模式",
					},
					roleCard: {
						enabled: true,
						name: "",
						personality: "",
						scenario: "",
						instructions: "",
						firstMessage: "",
					},
					worldBook: {
						enabled: false,
						entries: [],
					},
					memoryPolicy: {
						workingRetentionDays: 14,
						lowQualityThreshold: 0.55,
						includeStaleWorking: true,
						includeLowQuality: true,
						includeExactDuplicates: true,
					},
				},
			},
			activeWorkspaceId: "ws-1",
			workspaces: [],
			recentWorkspaceIds: [],
			setActiveWorkspace: vi.fn(),
			createWorkspaceRemote: vi.fn(),
			deleteWorkspaceRemote: vi.fn(),
			updateWorkspaceRemote: vi.fn().mockResolvedValue(undefined),
			updateWorkspaceContext: vi.fn(),
			syncFromBackend: vi.fn(),
		}),
	};
});

vi.mock("element-plus", () => ({
	ElMessage: {
		warning: vi.fn(),
		success: vi.fn(),
		info: vi.fn(),
		error: vi.fn(),
	},
	ElMessageBox: {
		confirm: messageBoxMocks.confirm,
	},
}));

const global = {
	directives: {
		loading: () => undefined,
	},
	stubs: {
		PanelShell: {
			template: '<section><slot name="actions" /><slot /></section>',
		},
		AsyncState: { template: "<div><slot /></div>" },
		"el-card": {
			template: '<section><slot name="header" /><slot /></section>',
		},
		"el-descriptions": { template: "<section><slot /></section>" },
		"el-descriptions-item": {
			props: ["label"],
			template: "<div><span>{{ label }}</span><slot /></div>",
		},
		"el-dialog": { template: "<div><slot /></div>" },
		"el-divider": { template: "<hr />" },
		"el-tag": { template: "<span><slot /></span>" },
		"el-button": { template: "<button><slot /></button>" },
		"el-icon": { template: "<i><slot /></i>" },
		"el-select": { template: "<select><slot /></select>" },
		"el-option": { template: "<option><slot /></option>" },
		"el-empty": { template: "<div />" },
		"el-progress": { template: "<div />" },
		"el-radio-group": { template: "<div><slot /></div>" },
		"el-radio-button": { template: "<button><slot /></button>" },
		"el-switch": { template: "<input />" },
		"el-input": {
			props: ["modelValue", "placeholder"],
			emits: ["update:modelValue"],
			template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
		},
		"el-input-number": { template: "<input />" },
		"el-row": { template: "<div><slot /></div>" },
		"el-col": { template: "<div><slot /></div>" },
		"el-alert": {
			props: ["title", "description"],
			template: "<div>{{ title }} {{ description }}</div>",
		},
		"el-form": { template: "<form><slot /></form>" },
		"el-form-item": { template: "<label><slot /></label>" },
		"el-slider": { template: "<input />" },
		"el-table": { template: "<table><slot /></table>" },
		"el-table-column": { template: "<td />" },
		"el-tabs": { template: "<section><slot /></section>" },
		"el-tab-pane": {
			props: ["label", "name"],
			template: "<div><slot /></div>",
		},
		"el-timeline": { template: "<div><slot /></div>" },
		"el-timeline-item": {
			props: ["timestamp"],
			template: "<div>{{ timestamp }}<slot /></div>",
		},
		"router-link": {
			props: ["to"],
			template: "<a><slot /></a>",
		},
	},
};

describe("refactor surface component integration", () => {
	beforeEach(() => {
		setActivePinia(createPinia());
		window.localStorage.clear();
		systemClientMocks.setModelSelection.mockReset();
		systemClientMocks.updateCompanionIdleProfile.mockReset();
		systemClientMocks.saveSettings.mockReset();
		memoryClientMocks.getIndexStatus.mockReset();
		memoryClientMocks.removeDoc.mockReset();
		memoryClientMocks.removeDocs.mockReset();
		memoryClientMocks.previewMaintenance.mockReset();
		memoryClientMocks.applyMaintenance.mockReset();
		systemClientMocks.setModelSelection.mockResolvedValue(undefined);
		systemClientMocks.updateCompanionIdleProfile.mockResolvedValue(undefined);
		systemClientMocks.saveSettings.mockResolvedValue(undefined);
		systemClientMocks.companionRuntime.mockResolvedValue({
			heartbeat: {
				behavior_events: [
					{
						type: "idle_prompt",
						emotion_id: "happy",
						motion_group: "Tap",
						message: "hello",
						trigger_reason: "gentle-support",
					},
				],
			},
			companion_state: {
				mood: "warm",
				stage: "stable",
				trust: 0.8,
				intimacy: 0.7,
				interruptibility: 0.6,
				fatigue: 0.1,
				proactive_state: {
					can_proactively_reach_out: true,
					readiness_band: "high",
					trigger_reason: "gentle-support",
				},
				behavior_profile: {
					tone_bucket: "soft",
					closeness_bucket: "close",
					expression_bucket: "expressive",
					initiative_bucket: "proactive",
				},
			},
			memory_state: {
				profile_count: 2,
				semantic_count: 1,
				episodic_count: 0,
				relationship_count: 3,
				working_count: 1,
				reflective_count: 4,
				recent_signals: [
					{
						kind: "support_request",
						layer: "relationship",
						source: "test",
						importance: 0.9,
						text: "help me",
						timestamp: "",
					},
				],
				signal_summary: { support_request: 1 },
			},
			relationship: {
				events: [],
				grouped: {},
				milestones: [],
				summary: { relationship_stage: "stable" },
			},
			retrieval_strategy: {
				label: "style+support-signal-boosted",
				layers: ["relationship", "working", "profile"],
				reasoning: "support signal boost",
			},
		});
		systemClientMocks.orchestration.mockResolvedValue({
			agents: [
				{
					id: "yuizaki.task-router",
					name: "Task Router",
					role: "router",
					audience: "core",
					description: "routes tasks",
				},
			],
			skills: [
				{ id: "yuizaki.capability-routing", name: "Capability Routing" },
			],
			commands: [
				{
					id: "yuizaki.create-once-task",
					name: "Create Once Task",
					audience: "core",
					description: "create task",
					target: "/api/system/schedules/once",
				},
			],
			hooks: [],
			summary: { agents: 1, skills: 1, commands: 1, hooks: 0 },
		});
		memoryClientMocks.getIndexStatus.mockResolvedValue({
			status: "ready",
			count: 2,
			metadata: {
				recallable_count: 2,
			},
		});
		memoryClientMocks.removeDoc.mockResolvedValue({ ok: true });
		memoryClientMocks.removeDocs.mockResolvedValue({ ok: true, deleted_count: 1 });
		memoryClientMocks.previewMaintenance.mockResolvedValue({
			status: "preview",
			preview_token: "a".repeat(64),
			policy: {},
			summary: {
				scanned_count: 2,
				active_count: 2,
				delete_count: 1,
			},
			candidates: [
				{ id: "doc-review", text: "needs review", action: "delete", reasons: ["low_quality"], layer: "semantic" },
			],
		});
		memoryClientMocks.applyMaintenance.mockResolvedValue({ status: "purged", changed_ids: ["doc-review"], changed_count: 1 });
		messageBoxMocks.confirm.mockReset();
		messageBoxMocks.confirm.mockResolvedValue(undefined);
		docs.value = [
			{
				id: "doc-1",
				text: "remembered preference",
				type: "preference",
				layer: "profile",
				importance: 0.9,
				confidence: 0.86,
				quality_score: 0.88,
				metadata: { scope: "workspace", workspace_id: "ws-1", source: "manual" },
			},
			{
				id: "doc-review",
				text: "needs review",
				type: "fact",
				layer: "semantic",
				importance: 0.5,
				confidence: 0.52,
				quality_score: 0.58,
				metadata: { scope: "workspace", workspace_id: "ws-1", source: "manual" },
			},
		];
	});

	it("renders CompanionPanel runtime snapshot state and behavior profile", async () => {
		const wrapper = mount(CompanionPanel, { global });
		await flushPromises();

		expect(wrapper.text()).toContain("gentle-support");
		expect(wrapper.text()).toContain("随时可以陪你");
		expect(wrapper.text()).toContain("support_request");
		expect(wrapper.text()).toContain("打开当前任务");
		expect(wrapper.text()).toContain("查看权限回执");
		expect(wrapper.text()).not.toContain("soft");
	});

	it("applies the active CompanionPanel profile through the existing runtime bridge", async () => {
		mount(CompanionPanel, { global });
		await flushPromises();

		expect(systemClientMocks.setModelSelection).toHaveBeenCalledWith("yuizaki-live2d", "live2d");
	});

	it("renders TasksPanel orchestration commands, skills, and owning agents", async () => {
		const wrapper = mount(TasksPanel, { global });
		await flushPromises();

		expect(wrapper.text()).toContain("Create Once Task");
		expect(wrapper.text()).toContain("Capability Routing");
		expect(wrapper.text()).toContain("Task Router");
	});

	it("renders MemoryPanel retrieval strategy from companion runtime", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		expect(wrapper.text()).not.toContain("写入原始文档");
		expect(wrapper.text()).not.toContain("原始检索");
		expect(wrapper.text()).not.toContain("检索轨迹");
		expect(wrapper.text()).not.toContain("后端过滤 开启");
		expect(wrapper.find('[data-testid="memory-type-select"]').exists()).toBe(true);
		expect(wrapper.text()).not.toContain("如 preference");

		const advancedButton = wrapper.get('[data-testid="memory-advanced-tools-toggle"]');
		expect(advancedButton.attributes("aria-label")).toBe("高级工具");
		expect(advancedButton.attributes("aria-expanded")).toBe("false");
		const docMetadata = wrapper.get('[data-memory-id="doc-1"] .doc-meta').text();
		expect(docMetadata).toContain("手动");
		expect(docMetadata).toContain("工作区");
		expect(docMetadata).toContain("长期有效");
		await advancedButton.trigger("click");
		await flushPromises();

		expect(advancedButton.attributes("aria-expanded")).toBe("true");
		expect(wrapper.text()).toContain("style+support-signal-boosted");
		expect(wrapper.text()).toContain("relationship > working > profile");
		expect(wrapper.text()).toContain("写入原始文档");
		expect(wrapper.text()).toContain("原始检索");
		expect(wrapper.text()).toContain("检索轨迹");
		expect(wrapper.text()).toContain("召回 1");
		expect(wrapper.text()).toContain("作用域 workspace");
		expect(wrapper.text()).toContain("候选 3/24");
		expect(wrapper.text()).toContain("后端过滤 开启");
		expect(wrapper.text()).toContain("workspace 2");
		expect(wrapper.text()).toContain("doc-1");
		expect(wrapper.text()).toContain("2/2 条可召回");
		expect(wrapper.text()).toContain("活跃记忆2");
		expect(wrapper.text()).toContain("1 条低置信；1 条低质量");
		expect(wrapper.text()).toContain("可召回 2");
		expect(wrapper.text()).toContain("待复核 1");
		expect(wrapper.text()).toContain("默认记忆范围");
		expect(wrapper.text()).toContain("保存面板修改");
		expect(wrapper.text()).toContain("先筛选再删除");
		expect(wrapper.text()).toContain("长期记忆维护");
		expect(wrapper.text()).toContain("永久清理");
	});

	it("connects MemoryPanel maintenance controls to the scoped backend contract", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		const previewButton = wrapper.findAll("button").find((button) => button.text().includes("预览影响"));
		await previewButton?.trigger("click");
		await flushPromises();

		expect(memoryClientMocks.previewMaintenance).toHaveBeenCalledWith(expect.objectContaining({
			scope: "workspace",
			workspace_id: "ws-1",
			working_retention_days: 14,
			low_quality_threshold: 0.55,
			include_stale_working: true,
			include_low_quality: true,
			include_exact_duplicates: true,
		}));
		expect(wrapper.text()).toContain("永久清理1");

		const applyButton = wrapper.findAll("button").find((button) => button.text().includes("永久清理"));
		await applyButton?.trigger("click");
		await flushPromises();

		expect(memoryClientMocks.applyMaintenance).toHaveBeenCalledWith(expect.objectContaining({
			confirmation: "PERMANENT_DELETE",
			preview_token: "a".repeat(64),
			scope: "workspace",
			workspace_id: "ws-1",
		}));
		expect(messageBoxMocks.confirm).toHaveBeenCalledWith(
			"将永久清理 1 条记忆，操作不可恢复。",
			"永久清理记忆",
			expect.objectContaining({ confirmButtonText: "永久清理", cancelButtonText: "取消", type: "warning" }),
		);
	});

	it("does not apply permanent memory maintenance when confirmation is cancelled", async () => {
		messageBoxMocks.confirm.mockRejectedValueOnce(new Error("cancel"));
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		const previewButton = wrapper.findAll("button").find((button) => button.text().includes("预览影响"));
		await previewButton?.trigger("click");
		await flushPromises();
		const applyButton = wrapper.findAll("button").find((button) => button.text().includes("永久清理"));
		await applyButton?.trigger("click");
		await flushPromises();

		expect(memoryClientMocks.applyMaintenance).not.toHaveBeenCalled();
	});

	it("does not delete filtered or selected memories when confirmation is cancelled", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		await wrapper.get('input[placeholder="搜索内容"]').setValue("remembered");
		await flushPromises();
		messageBoxMocks.confirm.mockRejectedValueOnce(new Error("cancel"));
		const batchDeleteButton = wrapper.findAll("button").find((button) => button.text().includes("永久删除筛选结果"));
		await batchDeleteButton?.trigger("click");
		await flushPromises();

		expect(messageBoxMocks.confirm).toHaveBeenCalledWith(
			"这些记忆将从存储中永久删除。",
			"永久删除 1 条记忆",
			expect.objectContaining({ confirmButtonText: "永久删除", cancelButtonText: "取消", type: "warning" }),
		);
		expect(memoryClientMocks.removeDocs).not.toHaveBeenCalled();

		await wrapper.get('[data-memory-id="doc-1"]').trigger("click");
		messageBoxMocks.confirm.mockRejectedValueOnce(new Error("cancel"));
		await wrapper.get('[data-testid="memory-inspector-delete"]').trigger("click");
		await flushPromises();

		expect(messageBoxMocks.confirm).toHaveBeenLastCalledWith(
			"这条记忆将从存储中永久删除。",
			"永久删除记忆",
			expect.objectContaining({ confirmButtonText: "永久删除", cancelButtonText: "取消", type: "warning" }),
		);
		expect(memoryClientMocks.removeDoc).not.toHaveBeenCalled();
	});

	it("renders large MemoryPanel document lists in batches", async () => {
		docs.value = Array.from({ length: 95 }, (_, index) => ({
			id: `doc-${String(index + 1).padStart(3, "0")}`,
			text: `memory item ${index + 1}`,
			type: "fact",
			layer: "semantic",
			importance: 0.5,
			confidence: 0.9,
			quality_score: 0.9,
			metadata: { scope: "workspace", workspace_id: "ws-1", source: "manual" },
		}));

		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		expect(wrapper.findAll(".memory-doc-card")).toHaveLength(80);
		const moreButton = wrapper
			.findAll("button")
			.find((button) => button.text().includes("显示更多 15 条"));
		expect(moreButton).toBeTruthy();

		await moreButton?.trigger("click");
		await flushPromises();

		expect(wrapper.findAll(".memory-doc-card")).toHaveLength(95);
		expect(wrapper.text()).not.toContain("显示更多");
	});
});
