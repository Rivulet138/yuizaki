import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import MemoryPanel from "../domains/memory/views/MemoryPanel.vue";
import MemoryReviewQueue from "../domains/memory/components/MemoryReviewQueue.vue";
import MemoryOverview from "../domains/memory/components/MemoryOverview.vue";

const systemClientMocks = vi.hoisted(() => ({
	companionRuntime: vi.fn(),
	orchestration: vi.fn(),
	setModelSelection: vi.fn(),
	updateCompanionIdleProfile: vi.fn(),
	saveSettings: vi.fn(),
}));

const memoryClientMocks = vi.hoisted(() => ({
	getCandidates: vi.fn(),
	exportDocs: vi.fn(),
	importDocs: vi.fn(),
	reviewCandidate: vi.fn(),
	getIndexStatus: vi.fn(),
	removeDoc: vi.fn(),
	removeDocs: vi.fn(),
	previewDelete: vi.fn(),
	previewMaintenance: vi.fn(),
	applyMaintenance: vi.fn(),
	rollbackDoc: vi.fn(),
	recordRecallFeedback: vi.fn().mockResolvedValue({ status: "recorded", id: "doc-1", feedback: "helpful", counts: { helpful: 1 } }),
}));

const memoryDomainMocks = vi.hoisted(() => ({
	loadDocs: vi.fn(),
	loadCandidates: vi.fn(),
	loadOverview: vi.fn(),
	loadForgottenDocs: vi.fn(),
	softForgetDoc: vi.fn(),
	restoreDoc: vi.fn(),
	updateDoc: vi.fn(),
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
		getCandidates: memoryClientMocks.getCandidates,
		exportDocs: memoryClientMocks.exportDocs,
		importDocs: memoryClientMocks.importDocs,
		reviewCandidate: memoryClientMocks.reviewCandidate,
		getIndexStatus: memoryClientMocks.getIndexStatus,
		removeDoc: memoryClientMocks.removeDoc,
		removeDocs: memoryClientMocks.removeDocs,
		previewDelete: memoryClientMocks.previewDelete,
		previewMaintenance: memoryClientMocks.previewMaintenance,
		applyMaintenance: memoryClientMocks.applyMaintenance,
		rollbackDoc: memoryClientMocks.rollbackDoc,
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
const forgottenDocs = ref<any[]>([]);
const reviewCandidates = ref<any[]>([]);
const overview = ref<any>(null);
const overviewRequest = ref({ loading: false, error: "" });
const candidatesRequest = ref({ loading: false, error: "" });
const queryResult = ref({
	query: "remember preference",
	results: [{
		id: "doc-1",
		score: 0.9,
		text: "remembered preference",
		why_recalled: "与当前请求直接匹配",
		evidence_type: "anchor",
		score_components: { semantic: 0.92, lexical: 0.4, recency: 0.8, quality: 0.88, learned: 0.1, final: 0.9 },
	}],
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
		forgottenDocs,
		reviewCandidates,
		overview,
		queryResult,
		docsRequest: ref({ loading: false, error: "" }),
		forgottenDocsRequest: ref({ loading: false, error: "" }),
		overviewRequest,
		candidatesRequest,
		addRequest: ref({ loading: false, error: "" }),
		updateRequest: ref({ loading: false, error: "" }),
		queryRequest: ref({ loading: false, error: "" }),
		rawQueryRequest: ref({ loading: false, error: "" }),
		loadDocs: memoryDomainMocks.loadDocs,
		loadOverview: memoryDomainMocks.loadOverview,
		loadForgottenDocs: memoryDomainMocks.loadForgottenDocs,
		loadCandidates: memoryDomainMocks.loadCandidates,
		addMemory: vi.fn().mockResolvedValue({ status: "ok" }),
		updateDoc: memoryDomainMocks.updateDoc,
		softForgetDoc: memoryDomainMocks.softForgetDoc,
		restoreDoc: memoryDomainMocks.restoreDoc,
		reviewCandidate: memoryClientMocks.reviewCandidate,
		queryMemory: vi.fn().mockResolvedValue(undefined),
		queryRawRag: vi.fn().mockResolvedValue(undefined),
		recordRecallFeedback: memoryClientMocks.recordRecallFeedback,
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
		"el-drawer": {
			props: ["modelValue", "title"],
			template: '<aside v-if="modelValue"><h2>{{ title }}</h2><slot /></aside>',
		},
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
		memoryClientMocks.getCandidates.mockReset();
		memoryClientMocks.exportDocs.mockReset().mockResolvedValue({
			format: "yuizaki-memory-export",
			version: 1,
			exported_at: "2026-08-26T00:00:00Z",
			scope: "workspace",
			include_state: "all",
			count: 2,
			docs: [],
		});
		memoryClientMocks.importDocs.mockReset().mockResolvedValue({
			status: "ok",
			imported_ids: [],
			imported_count: 0,
			skipped: [],
			skipped_count: 0,
			scope: "workspace",
		});
		memoryClientMocks.reviewCandidate.mockReset().mockResolvedValue({ status: "approved", id: "candidate-1" });
		memoryClientMocks.removeDoc.mockReset();
		memoryClientMocks.removeDocs.mockReset();
		memoryClientMocks.previewDelete.mockReset().mockResolvedValue({
			status: "preview",
			ids: ["doc-1"],
			total_count: 1,
			hard_delete_count: 1,
			candidate_tombstone_count: 0,
			affected_message_count: 0,
			effects: { authority_store: "delete_or_tombstone", index: "entries_removed", chat_references: "unchanged", recoverable: false },
		});
		memoryClientMocks.previewMaintenance.mockReset();
		memoryClientMocks.applyMaintenance.mockReset();
		memoryClientMocks.rollbackDoc.mockReset();
		memoryDomainMocks.loadDocs.mockReset().mockResolvedValue(undefined);
		memoryDomainMocks.loadCandidates.mockReset().mockResolvedValue(undefined);
		memoryDomainMocks.loadOverview.mockReset().mockResolvedValue(undefined);
		memoryDomainMocks.loadForgottenDocs.mockReset().mockResolvedValue(undefined);
		memoryDomainMocks.softForgetDoc.mockReset().mockResolvedValue({ status: "forgotten" });
		memoryDomainMocks.restoreDoc.mockReset().mockResolvedValue({ status: "restored" });
		memoryDomainMocks.updateDoc.mockReset().mockResolvedValue({ status: "updated" });
		reviewCandidates.value = [];
		overviewRequest.value = { loading: false, error: "" };
		candidatesRequest.value = { loading: false, error: "" };
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
		memoryClientMocks.rollbackDoc.mockResolvedValue({ status: "rolled_back", id: "doc-1", revision: 3 });
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
				valid_from: "2026-08-14T02:00:00.000Z",
				valid_to: "2026-09-14T02:00:00.000Z",
				expires_at: "2026-10-14T02:00:00.000Z",
				revision: 4,
				metadata: {
					scope: "workspace", workspace_id: "ws-1", source: "manual",
					valid_from: "2026-08-14T02:00:00.000Z",
					valid_to: "2026-09-14T02:00:00.000Z",
					expires_at: "2026-10-14T02:00:00.000Z",
					version_history: [{ revision: 3, text: "previous preference", metadata: { updated_at: "2026-08-13T02:00:00.000Z" } }],
				},
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
		reviewCandidates.value = [docs.value[1]];
		forgottenDocs.value = [
			{
				id: "doc-forgotten",
				text: "old preference",
				type: "preference",
				layer: "profile",
				state: "forgotten",
				metadata: { scope: "workspace", workspace_id: "ws-1", source: "manual", soft_forgotten: true },
			},
		];
		overview.value = {
			total: 3,
			recallable: 2,
			by_state: { active: 2, forgotten: 1 },
			by_layer: { profile: 1, semantic: 1 },
			by_source: { manual: 3 },
			by_review_status: { pending: 1 },
			index_health: { status: "ready", healthy: true },
			latest_activity: [{ id: "doc-1", text: "remembered preference", state: "active", layer: "profile", action: "updated", updated_at: "2026-08-14T12:00:00Z" }],
		};
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
		expect(advancedButton.attributes("aria-label")).toBe("打开高级工具");
		expect(advancedButton.attributes("aria-expanded")).toBe("false");
		expect(wrapper.get('[data-memory-id="doc-1"]').text()).toContain("remembered preference");
		expect(wrapper.text()).toContain("工作区");
		expect(wrapper.text()).toContain("手动");
		await advancedButton.trigger("click");
		await flushPromises();

		expect(advancedButton.attributes("aria-expanded")).toBe("true");
		expect(wrapper.text()).toContain("写入原始文档");
		expect(wrapper.text()).toContain("召回实验台");
		expect(wrapper.text()).toContain("检索轨迹");
		expect(wrapper.text()).toContain("召回 1 · 候选 3 · 过滤 2");
		expect(wrapper.text()).toContain("workspace 2");
		expect(wrapper.text()).toContain("doc-1");
		expect(wrapper.text()).toContain("可用性索引可用");
		expect(wrapper.text()).toContain("全部记忆3");
		expect(wrapper.text()).toContain("已停止召回1");
		expect(wrapper.text()).toContain("可召回2");
		expect(wrapper.text()).toContain("待确认1");
		expect(wrapper.text()).toContain("当前范围");
		expect(wrapper.text()).toContain("永久清理");
		expect(wrapper.find(".score-components").text()).toContain("语义0.9200");
		expect(wrapper.find(".score-components").text()).toContain("最终0.9000");
		expect(wrapper.text()).toContain("与当前请求直接匹配");
		expect(wrapper.text()).toContain("直接匹配");
		await wrapper.get('[data-memory-query-id="doc-1"] .feedback-row button').trigger("click");
		expect(memoryClientMocks.recordRecallFeedback).toHaveBeenCalledWith("doc-1", "helpful");
	});

	it("shows a retryable candidate error instead of an empty queue", async () => {
		candidatesRequest.value = { loading: false, error: "候选读取失败：控制服务不可用" };
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		const reviewQueue = wrapper.findComponent(MemoryReviewQueue);
		expect(reviewQueue.props("error")).toBe("候选读取失败：控制服务不可用");
		reviewQueue.vm.$emit("retry");
		await flushPromises();
		expect(memoryDomainMocks.loadCandidates).toHaveBeenCalled();
	});

	it("shows a direct retry action when the overview request fails", async () => {
		overviewRequest.value = { loading: false, error: "概览读取失败：控制服务不可用" };
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		const overviewPanel = wrapper.findComponent(MemoryOverview);
		expect(overviewPanel.props("error")).toBe("概览读取失败：控制服务不可用");
		overviewPanel.vm.$emit("retry");
		await flushPromises();
		expect(memoryDomainMocks.loadOverview).toHaveBeenCalled();
	});

	it("renders the per-record memory import report and storage effects", async () => {
		memoryClientMocks.importDocs.mockResolvedValueOnce({
			status: "ok",
			imported_ids: ["import-1"],
			imported_count: 1,
			skipped: [{ id: "import-duplicate", reason: "id_exists" }],
			skipped_count: 1,
			skipped_reason_counts: { id_exists: 1 },
			restored_soft_forgotten_count: 1,
			effects: { authority_store: "updated", index: "rebuild_required", chat_references: "preserved" },
			scope: "workspace",
		});
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();
		const input = wrapper.get('input[aria-label="选择记忆备份文件"]');
		Object.defineProperty(input.element, "files", {
			configurable: true,
			value: [{
				size: 128,
				text: vi.fn().mockResolvedValue(JSON.stringify({
					format: "yuizaki-memory-export",
					version: 1,
					docs: [{ id: "import-1", text: "restored memory", metadata: {} }],
				})),
			}],
		});

		await input.trigger("change");
		await flushPromises();

		expect(wrapper.text()).toContain("最近一次导入结果");
		expect(wrapper.text()).toContain("恢复停止召回 1 条");
		expect(wrapper.text()).toContain("索引状态 需要重建");
		expect(wrapper.text()).toContain("ID 已存在：1");
		expect(wrapper.text()).toContain("import-duplicate");
	});

	it("supports roving keyboard navigation across memory tabs", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();
		await wrapper.get("#memory-tab-library").trigger("keydown", { key: "ArrowRight" });
		await flushPromises();
		expect(wrapper.get("#memory-tab-review").attributes("aria-selected")).toBe("true");
		expect(wrapper.get("#memory-tab-library").attributes("tabindex")).toBe("-1");
		await wrapper.get("#memory-tab-review").trigger("keydown", { key: "End" });
		await flushPromises();
		expect(wrapper.get("#memory-tab-overview").attributes("aria-selected")).toBe("true");
	});

	it("edits temporal metadata and rolls back a selected memory revision", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		expect(wrapper.text()).toContain("版本历史（1）");
		expect(wrapper.text()).toContain("previous preference");
		await wrapper.get('[data-testid="memory-valid-from"]').setValue("2026-08-20T10:30");
		await wrapper.get('[data-testid="memory-valid-to"]').setValue("");
		await wrapper.get('[data-testid="memory-expires-at"]').setValue("");
		await wrapper.get('[data-testid="memory-inspector-save"]').trigger("click");
		await flushPromises();

		expect(memoryDomainMocks.updateDoc).toHaveBeenCalledWith("doc-1", expect.objectContaining({
			metadata: expect.objectContaining({
				valid_from: new Date("2026-08-20T10:30").toISOString(),
				valid_to: null,
				expires_at: null,
			}),
		}));

		await wrapper.get('[data-testid="memory-rollback-3"]').trigger("click");
		await flushPromises();
		expect(memoryClientMocks.rollbackDoc).toHaveBeenCalledWith("doc-1", 3);
		expect(memoryDomainMocks.loadDocs).toHaveBeenCalled();
	});

	it("preserves timestamp seconds when saving a non-temporal inspector edit", async () => {
		docs.value[0].metadata.valid_from = "2026-08-14T02:00:37.123Z";
		docs.value[0].valid_from = "2026-08-14T02:00:37.123Z";
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		await wrapper.get('[data-testid="memory-inspector-text"]').setValue("updated preference");
		await wrapper.get('[data-testid="memory-inspector-save"]').trigger("click");
		await flushPromises();

		expect(memoryDomainMocks.updateDoc).toHaveBeenCalledWith("doc-1", expect.objectContaining({
			metadata: expect.objectContaining({ valid_from: "2026-08-14T02:00:37.123Z" }),
		}));
	});

	it("connects MemoryPanel maintenance controls to the scoped backend contract", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();
		await wrapper.get('[data-testid="memory-advanced-tools-toggle"]').trigger("click");
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
		expect(wrapper.text()).toContain("1 条待清理");

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
		await wrapper.get('[data-testid="memory-advanced-tools-toggle"]').trigger("click");
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

		await wrapper.get('input[placeholder="搜索记忆内容"]').setValue("remembered");
		await flushPromises();
		messageBoxMocks.confirm.mockRejectedValueOnce(new Error("cancel"));
		const batchDeleteButton = wrapper.findAll("button").find((button) => button.text().includes("永久删除筛选结果"));
		await batchDeleteButton?.trigger("click");
		await flushPromises();

		expect(messageBoxMocks.confirm).toHaveBeenCalledWith(
			"共 1 条：1 条物理删除；索引对应条目会移除，操作不可恢复。",
			"永久删除 1 条记忆",
			expect.objectContaining({ confirmButtonText: "永久删除", cancelButtonText: "取消", type: "warning" }),
		);
		expect(memoryClientMocks.removeDocs).not.toHaveBeenCalled();

		await wrapper.get('[data-memory-id="doc-1"]').trigger("click");
		messageBoxMocks.confirm.mockRejectedValueOnce(new Error("cancel"));
		await wrapper.get('[data-testid="memory-inspector-delete"]').trigger("click");
		await flushPromises();

		expect(messageBoxMocks.confirm).toHaveBeenLastCalledWith(
			"共 1 条：1 条物理删除；索引对应条目会移除，操作不可恢复。",
			"永久删除记忆",
			expect.objectContaining({ confirmButtonText: "永久删除", cancelButtonText: "取消", type: "warning" }),
		);
		expect(memoryClientMocks.removeDoc).not.toHaveBeenCalled();
	});

	it("stops recall by default and restores the memory from overview", async () => {
		const wrapper = mount(MemoryPanel, { global });
		await flushPromises();

		await wrapper.get('[data-testid="memory-inspector-forget"]').trigger("click");
		await flushPromises();

		expect(messageBoxMocks.confirm).toHaveBeenCalledWith(
			"停止召回后，这条记忆不会再参与回答；你仍可在概览中恢复。",
			"停止召回这条记忆",
			expect.objectContaining({ confirmButtonText: "停止召回", cancelButtonText: "取消" }),
		);
		expect(memoryDomainMocks.softForgetDoc).toHaveBeenCalledWith("doc-1", { reason: "user_soft_forget" });

		await wrapper.get("#memory-tab-overview").trigger("click");
		await wrapper.get('[data-testid="memory-restore-doc-forgotten"]').trigger("click");
		await flushPromises();

		expect(memoryDomainMocks.restoreDoc).toHaveBeenCalledWith("doc-forgotten", { reason: "user_restore" });
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

		expect(wrapper.findAll(".memory-row")).toHaveLength(80);
		const moreButton = wrapper
			.findAll("button")
			.find((button) => button.text().includes("再显示 15 条"));
		expect(moreButton).toBeTruthy();

		await moreButton?.trigger("click");
		await flushPromises();

		expect(wrapper.findAll(".memory-row")).toHaveLength(95);
		expect(wrapper.text()).not.toContain("再显示");
	});
});
