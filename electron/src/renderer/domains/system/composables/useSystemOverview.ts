import { ElMessage } from "element-plus";
import { ref } from "vue";
import { useDomainRequest } from "@/shared/composables/useDomainRequest";
import { useSystemStore } from "@/stores/systemStore";
import { petControl } from "@/utils/petControl";
import { summaryClient } from "@/api/client";
import type { SummaryDetailResponse } from "@/api/clients/summary-client";
import type {
	PetControlState,
	PetModelCatalogPayload,
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

	const summarySessions = ref<SummarySession[]>([]);
	const selectedSummaryDetail = ref<SummaryDetailResponse | null>(null);

	const summaryReady = ref(false);
	const readinessMessage = ref("");
	const selectedSummarySessionId = ref("");

	const summarySessionsReq = useDomainRequest<{ sessions: unknown[] }>();
	const summaryDetailReq = useDomainRequest<SummaryDetailResponse>();
	const readinessReq = useDomainRequest<ReadinessPayload>();
	const rewriteReq = useDomainRequest<RewriteSummaryPayload>();

	const loadSummarySessions = async () => {
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
		if (!sessionId) return null;
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

	const rewriteSummary = async () => {
		if (!selectedSummarySessionId.value) return;
		const res = await rewriteReq.execute(() =>
			summaryClient.rewriteSummary(selectedSummarySessionId.value),
		);
		if (res?.ok) {
			ElMessage.success("摘要重写完成");
			await loadSummarySessions();
		} else {
			ElMessage.error(rewriteReq.error || "手动重写摘要失败");
		}
	};

	const syncPetData = async (silent: boolean = true, includeCatalog = true) => {
		try {
			const [state, catalog] = await Promise.all([
				petControl.getState(),
				includeCatalog ? petControl.getCatalog() : Promise.resolve(null),
			]);
			if (catalog) {
				petCatalog.value.activeModelId = catalog.activeModelId;
				petCatalog.value.models = catalog.models;
			}

			Object.assign(petState.value, state);
			scaleDraft.value = Number(state.scale.toFixed(2));
			opacityDraft.value = Number(state.opacity.toFixed(2));
			selectedModelId.value =
				state.modelId ?? petCatalog.value.activeModelId ?? petCatalog.value.models[0]?.id ?? null;
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

	return {
		systemStore,
		petState,
		petCatalog,
		scaleDraft,
		opacityDraft,
		selectedModelId,
		summarySessions,
		selectedSummaryDetail,
		summaryReady,
		readinessMessage,
		selectedSummarySessionId,
		summarySessionsReq,
		summaryDetailReq,
		readinessReq,
		rewriteReq,
		loadSummarySessions,
		loadSummaryDetail,
		refreshReadiness,
		rewriteSummary,
		syncPetData,
		applyModel,
		applyScale,
		applyOpacity,
		setPetVisible,
		setDoNotDisturb,
		setInteractMode,
		setClickThrough,
		setLocked,
		dockBottomRight,
	};
}
