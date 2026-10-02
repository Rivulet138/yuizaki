import { ElMessage } from "element-plus";
import { ref } from "vue";
import { useSystemStore } from "@/stores/systemStore";
import { petControl } from "@/utils/petControl";
import type {
	PetControlState,
	PetModelCatalogPayload,
} from "../../../../shared/pet-control";
import { DEFAULT_PET_CONTROL_STATE } from "../../../../shared/pet-control";

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
