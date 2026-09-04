import { logger } from "./logger";
import { PetRenderer } from "./pet-renderer";

type PetRendererWindow = {
	live2dApi?: typeof window.live2dApi;
	petRenderer?: PetRenderer;
};

const petWindow = window as unknown as PetRendererWindow;

if (!petWindow.live2dApi) {
	const fallbackApi = {
		pet: {
			rendererReady: () => {},
			setPosition: () => {},
			dragWindow: () => {},
			endWindowDrag: () => {},
			setMouseIgnore: () => {},
			setLocked: async () => ({
				modelType: "live2d",
				modelId: null,
				scale: 0.42,
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
				scale: 0.42,
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
				scale: 0.42,
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
			openChatCenter: () => {},
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

// The renderer registers IPC listeners during init. Expose the preload API first
// so a slow or failed preload cannot leave an apparently live but disconnected pet.
const renderer = new PetRenderer("pet-canvas");
petWindow.petRenderer = renderer;
renderer.init().catch((error) => {
	logger.error("[PetRenderer] init failed:", error);
});
