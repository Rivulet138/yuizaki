import { logger } from "./logger";
import { PetRenderer } from "./pet-renderer";
import { DEFAULT_PET_TEST_STATE, type PetTestState } from "./pet-test-state";

type PetRendererWindow = {
	live2dApi?: typeof window.live2dApi;
	petRenderer?: PetRenderer;
	__petTestState?: PetTestState;
};

const renderer = new PetRenderer("pet-canvas");
renderer.init().catch((error) => {
	logger.error("[PetRenderer] init failed:", error);
});

const petWindow = window as unknown as PetRendererWindow;

if (!petWindow.live2dApi) {
	const readTestState = (): PetTestState => ({
		...DEFAULT_PET_TEST_STATE,
		...(petWindow.__petTestState ?? {}),
	});
	const fallbackApi = {
		pet: {
			rendererReady: () => {},
			setPosition: () => {},
			dragWindow: () => {
				const current = readTestState();
				petWindow.__petTestState = {
					...current,
					dragMoveCount: current.dragMoveCount + 1,
					lastDragStartAt: current.lastDragStartAt ?? Date.now(),
				};
			},
			endWindowDrag: () => {
				const current = readTestState();
				petWindow.__petTestState = {
					...current,
					lastDragEndAt: Date.now(),
				};
			},
			setMouseIgnore: () => {},
			setLocked: async () => ({
				modelType: "live2d",
				modelId: null,
				scale: 0.28,
				positionX: 0,
				positionY: 0,
				placement: "bottom-right",
				interactMode: false,
				clickThrough: true,
				locked: false,
				opacity: 1,
				ready: false,
			}),
			setClickThrough: async () => ({
				modelType: "live2d",
				modelId: null,
				scale: 0.28,
				positionX: 0,
				positionY: 0,
				placement: "bottom-right",
				interactMode: false,
				clickThrough: true,
				locked: false,
				opacity: 1,
				ready: false,
			}),
			snapBottomRight: async () => ({
				modelType: "live2d",
				modelId: null,
				scale: 0.28,
				positionX: 0,
				positionY: 0,
				placement: "bottom-right",
				interactMode: false,
				clickThrough: true,
				locked: false,
				opacity: 1,
				ready: false,
			}),
			reloadRenderer: async () => ({ success: true }),
			setExpression: () => {},
			playAnimation: () => {},
			saveScale: () => {},
			savePosition: () => {},
			reportState: () => {},
			reportAvatarCapabilities: () => {},
			reportAvatarCommandResult: () => {},
			reportLipSyncReady: () => {},
			openControlPanel: () => {},
			openChatCenter: () => {
				const current = readTestState();
				petWindow.__petTestState = {
					...current,
					lastChatCenterRequestAt: Date.now(),
				};
			},
			dispatchEvent: async () => ({
				ok: true,
				matched: 0,
				dispatched: 0,
				skipped: 0,
				results: [],
			}),
		},
		interact: {
			enable: () => {},
			disable: () => {},
		},
		on: () => {},
		off: () => {},
	} satisfies typeof window.live2dApi;
	petWindow.live2dApi = fallbackApi;
}

petWindow.petRenderer = renderer;
petWindow.__petTestState = petWindow.__petTestState ?? {
	...DEFAULT_PET_TEST_STATE,
};
