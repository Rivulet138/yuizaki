import { logger } from "./logger";
import { PetRenderer } from "./pet-renderer";
import {
	DEFAULT_PET_CONTROL_STATE,
	type PetControlState,
} from "../shared/pet-control";

type PetRendererWindow = {
	live2dApi?: typeof window.live2dApi;
	petRenderer?: PetRenderer;
};

const petWindow = window as unknown as PetRendererWindow;

if (!petWindow.live2dApi) {
	const fallbackState: PetControlState = { ...DEFAULT_PET_CONTROL_STATE };
	const fallbackApi = {
		pet: {
			rendererReady: () => {},
			setPosition: () => {},
			dragWindow: () => {},
			endWindowDrag: () => {},
			setMouseIgnore: () => {},
		setLocked: async () => ({ ...fallbackState }),
		setClickThrough: async () => ({ ...fallbackState }),
		completeAdjustment: async () => ({ ...fallbackState }),
		cancelAdjustment: async () => ({ ...fallbackState }),
		snapBottomRight: async () => ({ ...fallbackState }),
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
			enable: async () => ({ ...fallbackState }),
			disable: async () => ({ ...fallbackState }),
		},
		on: () => {},
		off: () => {},
	} satisfies typeof window.live2dApi;
	petWindow.live2dApi = fallbackApi;
}

// Cubism Core is loaded synchronously by pet-window.html before this module.
// The renderer registers IPC listeners during init. Expose the preload API first
// so a slow or failed preload cannot leave an apparently live but disconnected pet.
const renderer = new PetRenderer("pet-canvas");
petWindow.petRenderer = renderer;
renderer.init().catch((error) => {
	logger.error("[PetRenderer] bootstrap failed:", error);
});
