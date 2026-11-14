import { ElMessage } from "element-plus";
import { ref } from "vue";
import { useSystemStore } from "@/stores/systemStore";
import { petControl } from "@/utils/petControl";
import { t } from "@/i18n";
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

	// Versions only guard frontend snapshots; successful operation ACKs remain independent.
	let syncSequence = 0;
	let catalogSequence = 0;

	const syncPetData = async (silent: boolean = true, includeCatalog = true) => {
		const sequence = ++syncSequence;
		const catalogVersion = includeCatalog ? ++catalogSequence : null;
		try {
			const [state, catalog] = await Promise.all([
				petControl.getState(),
				includeCatalog ? petControl.getCatalog() : Promise.resolve(null),
			]);
			// Pet edits and state-only polls do not invalidate a requested catalog.
			if (catalog && catalogVersion === catalogSequence) {
				petCatalog.value.activeModelId = catalog.activeModelId;
				petCatalog.value.models = catalog.models;
				selectedModelId.value ??=
					petState.value.modelId ?? catalog.activeModelId ?? catalog.models[0]?.id ?? null;
			}
			if (sequence !== syncSequence) return;

			Object.assign(petState.value, state);
			scaleDraft.value = Number(state.scale.toFixed(2));
			opacityDraft.value = Number(state.opacity.toFixed(2));
			selectedModelId.value =
				state.modelId ?? petCatalog.value.activeModelId ?? petCatalog.value.models[0]?.id ?? null;
		} catch {
			if (!silent) ElMessage.error(t("overview.petControlUnreachable"));
		}
	};

	const reloadVisiblePetLayer = async () => {
		await petControl.setVisible(true);
		await petControl.reloadRenderer();
	};

	const applyModel = async () => {
		if (!selectedModelId.value) return;
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setModel(selectedModelId.value);
			if (sequence === syncSequence) Object.assign(petState.value, state);
			await reloadVisiblePetLayer();
			if (sequence === syncSequence) await syncPetData(true);
			ElMessage.success(t("overview.modelSwitched"));
		} catch {
			ElMessage.error(t("overview.modelSwitchFailed"));
		}
	};

	const applyScale = async (value: number | number[]) => {
		const scale = Array.isArray(value) ? value[0] : value;
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setScale(scale);
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.scaleFailed"));
		}
	};

	const applyOpacity = async (value: number | number[]) => {
		const opacity = Array.isArray(value) ? value[0] : value;
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setOpacity(opacity);
			if (sequence === syncSequence) {
				Object.assign(petState.value, state);
				opacityDraft.value = Number(state.opacity.toFixed(2));
			}
		} catch {
			ElMessage.error(t("overview.opacityFailed"));
		}
	};

	const setInteractMode = async (enabled: string | number | boolean) => {
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setInteractMode(Boolean(enabled));
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.dragModeFailed"));
		}
	};

	const setClickThrough = async (enabled: string | number | boolean) => {
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setClickThrough(Boolean(enabled));
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.clickThroughFailed"));
		}
	};

	const setLocked = async (enabled: string | number | boolean) => {
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setLocked(Boolean(enabled));
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.positionLockFailed"));
		}
	};

	const setPetVisible = async (enabled: string | number | boolean) => {
		const sequence = ++syncSequence;
		try {
			await petControl.setVisible(Boolean(enabled));
			if (sequence === syncSequence) {
				petState.value.visible = Boolean(enabled);
				await syncPetData(true);
			}
		} catch {
			ElMessage.error(t("overview.visibilityFailed"));
		}
	};

	const setDoNotDisturb = async (enabled: string | number | boolean) => {
		const sequence = ++syncSequence;
		try {
			const state = await petControl.setDoNotDisturb(Boolean(enabled));
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.dndFailed"));
		}
	};

	const dockBottomRight = async () => {
		const sequence = ++syncSequence;
		try {
			await petControl.setVisible(true);
			const state = await petControl.snapBottomRight();
			if (sequence === syncSequence) Object.assign(petState.value, state);
		} catch {
			ElMessage.error(t("overview.snapFailed"));
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
