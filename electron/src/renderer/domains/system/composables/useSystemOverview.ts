import { ElMessage } from "element-plus";
import { computed, ref } from "vue";
import type {
	CompanionRuntimeSnapshot,
	HeartbeatBehaviorEvent,
	HeartbeatPersona,
	HeartbeatSnapshot,
} from "@/../shared/agent";
import { useDomainRequest } from "@/shared/composables/useDomainRequest";
import { useSystemStore } from "@/stores/systemStore";
import { petControl } from "@/utils/petControl";
import { summaryClient, systemClient } from "@/api/client";
import type { SummaryDetailResponse } from "@/api/clients/summary-client";
import type {
	PetControlState,
	PetModelCatalogPayload,
	PetModelDefinition,
} from "../../../../shared/pet-control";
import { DEFAULT_PET_CONTROL_STATE } from "../../../../shared/pet-control";

// --- Types ---
export interface SummaryStats {
	session_id: string;
	summary_length: number;
	updated_at: string | null;
	compression_count: number;
	rewrite_count: number;
	messages_since_rewrite: number;
	has_summary: boolean;
	effective_rewrite_interval: number;
	quality_band: "low" | "medium" | "high";
	quality_scorer: "rule" | "llm" | string;
	quality_basis: string;
	quality_score_cooldown_seconds: number;
	quality_score_budget_per_hour: number;
	quality: {
		overall: number;
		facts: number;
		preferences: number;
		goals_open_tasks: number;
	};
}

export interface SummarySession {
	session_id: string;
	summary: string;
	stats: SummaryStats;
}

export interface SummaryAuditLog {
	timestamp: string;
	session_id: string;
	source: "manual" | "auto" | string;
	outcome: "ok" | "error" | "timeout" | "skipped" | string;
	detail: string;
}

export interface GovernanceTrendRow {
	day: string;
	audit_total: number;
	ok_rate: number;
	guard_skip_rate: number;
	fallback_rate: number;
}

export interface GovernanceAlert {
	key: string;
	type: string;
	severity: "high" | "medium" | "low" | string;
	day: string;
	message: string;
	suggestion: string;
}

interface ReadinessCheck {
	ok?: boolean;
	message?: string;
}

interface ReadinessPayload {
	ready: boolean;
	checks?: Record<string, ReadinessCheck>;
}

interface RewriteSummaryPayload {
	ok?: boolean;
	message?: string;
}

export function useSystemOverview() {
	const systemStore = useSystemStore();

	const petState = ref<PetControlState>({ ...DEFAULT_PET_CONTROL_STATE });
	const petCatalog = ref<PetModelCatalogPayload>({
		activeModelId: null,
		models: [],
	});

	const scaleDraft = ref(DEFAULT_PET_CONTROL_STATE.scale);
	const opacityDraft = ref(DEFAULT_PET_CONTROL_STATE.opacity);
	const selectedModelId = ref<string | null>(DEFAULT_PET_CONTROL_STATE.modelId);
	const selectedEmotionId = ref("");
	const selectedMotionId = ref("");
	const selectedExpressionName = ref("");

	const summarySessions = ref<SummarySession[]>([]);
	const selectedSummaryDetail = ref<SummaryDetailResponse | null>(null);
	const auditLogs = ref<SummaryAuditLog[]>([]);
	const governanceTrends = ref<GovernanceTrendRow[]>([]);
	const governanceAlerts = ref<GovernanceAlert[]>([]);

	const heartbeatPersona = ref<HeartbeatPersona | null>(null);
	const latestBehaviorEvent = ref<HeartbeatBehaviorEvent | null>(null);

	const summaryReady = ref(false);
	const readinessMessage = ref("");
	const selectedSummarySessionId = ref("");

	const auditSessionFilter = ref<"all" | "selected">("selected");
	const auditSourceFilter = ref<"all" | "manual" | "auto">("all");
	const auditOutcomeFilter = ref<
		"all" | "ok" | "error" | "timeout" | "skipped"
	>("all");

	const summaryBackoffUntil = ref(0);

	const summarySessionsReq = useDomainRequest<{ sessions: unknown[] }>();
	const summaryDetailReq = useDomainRequest<SummaryDetailResponse>();
	const auditReq = useDomainRequest<{ logs: unknown[] }>();
	const govReportReq = useDomainRequest<{
		trends: unknown[];
		alerts: unknown[];
	}>();
	const readinessReq = useDomainRequest<ReadinessPayload>();
	const rewriteReq = useDomainRequest<RewriteSummaryPayload>();
	const alertActionReq = useDomainRequest<unknown>();
	const heartbeatReq = useDomainRequest<HeartbeatSnapshot>();
	const companionRuntimeReq = useDomainRequest<CompanionRuntimeSnapshot>();

	const loadSummarySessions = async () => {
		if (Date.now() < summaryBackoffUntil.value) return;
		const result = await summarySessionsReq.execute(() =>
			summaryClient.getSessions(),
		);
		if (result?.sessions) {
			summarySessions.value = result.sessions as SummarySession[];
			if (!selectedSummarySessionId.value && summarySessions.value.length > 0) {
				selectedSummarySessionId.value = summarySessions.value[0].session_id;
			}
			if (selectedSummarySessionId.value) {
				await loadSummaryDetail(selectedSummarySessionId.value);
			}
		}
	};

	const loadSummaryDetail = async (
		sessionId = selectedSummarySessionId.value,
	) => {
		if (!sessionId || Date.now() < summaryBackoffUntil.value) return null;
		const result = await summaryDetailReq.execute(() =>
			summaryClient.getSummary(sessionId),
		);
		selectedSummaryDetail.value = result ?? null;
		return result;
	};

	const refreshReadiness = async () => {
		const res = await readinessReq.execute(() => summaryClient.getReadiness());
		if (res) {
			const ready = Boolean(res.ready);
			const checks = res.checks ?? {};
			summaryReady.value =
				ready &&
				Boolean(checks.llm?.ok) &&
				Boolean(checks.tts?.ok) &&
				Boolean(checks.database?.ok);
			readinessMessage.value = summaryReady.value
				? "服务就绪"
				: String(checks.llm?.message || "后端服务尚未就绪");
		} else {
			summaryReady.value = false;
		}
	};

	const loadSummaryAudit = async () => {
		if (Date.now() < summaryBackoffUntil.value) return;
		const params: Record<string, string | number> = { limit: 120 };
		if (
			auditSessionFilter.value === "selected" &&
			selectedSummarySessionId.value
		) {
			params.session_id = selectedSummarySessionId.value;
		}
		const result = await auditReq.execute(() => summaryClient.getAudit(params));
		if (result?.logs) {
			auditLogs.value = result.logs as SummaryAuditLog[];
		}
	};

	const loadGovernanceReport = async () => {
		if (Date.now() < summaryBackoffUntil.value) return;
		const result = await govReportReq.execute(() =>
			summaryClient.getGovernanceReport(7),
		);
		if (result) {
			governanceTrends.value = (result.trends ?? []) as GovernanceTrendRow[];
			governanceAlerts.value = (result.alerts ?? []) as GovernanceAlert[];
		}
	};

	const loadHeartbeat = async () => {
		const runtime = await companionRuntimeReq.execute(() =>
			systemClient.companionRuntime(),
		);
		if (runtime) {
			heartbeatPersona.value = runtime.heartbeat.persona ?? null;
			latestBehaviorEvent.value =
				Array.isArray(runtime.heartbeat.behavior_events) &&
				runtime.heartbeat.behavior_events.length > 0
					? runtime.heartbeat.behavior_events[
							runtime.heartbeat.behavior_events.length - 1
						]
					: null;
			return;
		}

		const result = await heartbeatReq.execute(() => systemClient.heartbeat());
		if (result) {
			heartbeatPersona.value = result.persona ?? null;
			latestBehaviorEvent.value =
				Array.isArray(result.behavior_events) &&
				result.behavior_events.length > 0
					? result.behavior_events[result.behavior_events.length - 1]
					: null;
		}
	};

	const ackAlert = async (key: string) => {
		if (!key) return;
		await alertActionReq.execute(() => summaryClient.ackAlert(key));
		await loadGovernanceReport();
	};

	const snoozeAlert = async (key: string, minutes: number = 120) => {
		if (!key) return;
		await alertActionReq.execute(() => summaryClient.snoozeAlert(key, minutes));
		await loadGovernanceReport();
	};

	const clearAlerts = async () => {
		await alertActionReq.execute(() => summaryClient.clearAlerts());
		await loadGovernanceReport();
	};

	const rewriteSummary = async () => {
		if (!selectedSummarySessionId.value) return;
		const res = await rewriteReq.execute(() =>
			summaryClient.rewriteSummary(selectedSummarySessionId.value),
		);
		if (res?.ok) {
			ElMessage.success("摘要重写完成");
			await Promise.all([
				loadSummarySessions(),
				loadSummaryAudit(),
				loadSummaryDetail(),
			]);
		} else {
			ElMessage.error(rewriteReq.error || "手动重写摘要失败");
		}
	};

	const syncPetData = async (silent: boolean = true) => {
		try {
			const [state, catalog] = await Promise.all([
				petControl.getState(),
				petControl.getCatalog(),
			]);
			petCatalog.value.activeModelId = catalog.activeModelId;
			petCatalog.value.models = catalog.models;

			Object.assign(petState.value, state);
			scaleDraft.value = Number(state.scale.toFixed(2));
			opacityDraft.value = Number(state.opacity.toFixed(2));
			selectedModelId.value =
				state.modelId ?? catalog.activeModelId ?? catalog.models[0]?.id ?? null;
		} catch {
			if (!silent) ElMessage.error("无法连接桌宠控制服务");
		}
	};

	const reloadVisiblePetLayer = async () => {
		await petControl.setVisible(true);
		await petControl.reloadRenderer();
	};

	const applyModel = async () => {
		if (!selectedModelId.value) return;
		try {
			const state = await petControl.setModel(selectedModelId.value);
			Object.assign(petState.value, state);
			await reloadVisiblePetLayer();
			await syncPetData(true);
			ElMessage.success("桌宠模型已切换");
		} catch {
			ElMessage.error("切换桌宠模型失败");
		}
	};

	const applyScale = async (value: number | number[]) => {
		const scale = Array.isArray(value) ? value[0] : value;
		try {
			const state = await petControl.setScale(scale);
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("更新桌宠大小失败");
		}
	};

	const applyOpacity = async (value: number | number[]) => {
		const opacity = Array.isArray(value) ? value[0] : value;
		try {
			const state = await petControl.setOpacity(opacity);
			Object.assign(petState.value, state);
			opacityDraft.value = Number(state.opacity.toFixed(2));
		} catch {
			ElMessage.error("更新桌宠透明度失败");
		}
	};

	const triggerEmotionPreset = async () => {
		if (!selectedEmotionId.value) return;
		try {
			await petControl.triggerEmotion(selectedEmotionId.value);
		} catch {
			ElMessage.error("触发情绪预设失败");
		}
	};

	const triggerMotion = async (motionGroup?: string) => {
		const motion = currentModel.value?.motions.find(
			(item) => item.id === selectedMotionId.value,
		);
		const targetGroup = motionGroup || motion?.group;
		if (!targetGroup) return;
		try {
			await petControl.triggerMotion(targetGroup, 0);
		} catch {
			ElMessage.error("播放动作失败");
		}
	};

	const setInteractMode = async (enabled: string | number | boolean) => {
		try {
			const state = await petControl.setInteractMode(Boolean(enabled));
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("切换拖动模式失败");
		}
	};

	const setClickThrough = async (enabled: string | number | boolean) => {
		try {
			const state = await petControl.setClickThrough(Boolean(enabled));
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("切换鼠标穿透失败");
		}
	};

	const setLocked = async (enabled: string | number | boolean) => {
		try {
			const state = await petControl.setLocked(Boolean(enabled));
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("切换位置锁定失败");
		}
	};

	const setPetVisible = async (enabled: string | number | boolean) => {
		try {
			await petControl.setVisible(Boolean(enabled));
			petState.value.visible = Boolean(enabled);
			await syncPetData(true);
		} catch {
			ElMessage.error("切换桌宠显示状态失败");
		}
	};

	const setDoNotDisturb = async (enabled: string | number | boolean) => {
		try {
			const state = await petControl.setDoNotDisturb(Boolean(enabled));
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("切换免打扰失败");
		}
	};

	const dockBottomRight = async () => {
		try {
			await petControl.setVisible(true);
			const state = await petControl.snapBottomRight();
			Object.assign(petState.value, state);
		} catch {
			ElMessage.error("桌宠回到右下角失败");
		}
	};

	const currentModel = computed<PetModelDefinition | null>(() => {
		const activeId = petState.value.modelId ?? petCatalog.value.activeModelId;
		return (
			petCatalog.value.models.find((model) => model.id === activeId) ??
			petCatalog.value.models[0] ??
			null
		);
	});

	return {
		systemStore,
		petState,
		petCatalog,
		scaleDraft,
		opacityDraft,
		selectedModelId,
		selectedEmotionId,
		selectedMotionId,
		selectedExpressionName,
		summarySessions,
		selectedSummaryDetail,
		auditLogs,
		governanceTrends,
		governanceAlerts,
		heartbeatPersona,
		latestBehaviorEvent,
		summaryReady,
		readinessMessage,
		selectedSummarySessionId,
		auditSessionFilter,
		auditSourceFilter,
		auditOutcomeFilter,
		summarySessionsReq,
		summaryDetailReq,
		auditReq,
		govReportReq,
		readinessReq,
		alertActionReq,
		rewriteReq,
		heartbeatReq,
		loadSummarySessions,
		loadSummaryDetail,
		refreshReadiness,
		loadSummaryAudit,
		loadGovernanceReport,
		loadHeartbeat,
		ackAlert,
		snoozeAlert,
		clearAlerts,
		rewriteSummary,
		syncPetData,
		applyModel,
		applyScale,
		applyOpacity,
		triggerEmotionPreset,
		triggerMotion,
		setPetVisible,
		setDoNotDisturb,
		setInteractMode,
		setClickThrough,
		setLocked,
		dockBottomRight,
		currentModel,
	};
}
