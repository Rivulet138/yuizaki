import "pixi.js/unsafe-eval";
import type { Live2DSprite } from "easy-live2d";
import { Config as Live2DConfig } from "easy-live2d";
import * as PIXI from "pixi.js";
import {
	DEFAULT_PET_CONTROL_STATE,
	normalizePetLipSyncProfile,
	type AvatarManifest,
	type PetCompanionIdleProfile,
	type PetControlConfigPatch,
	type PetControlDirective,
	type PetExpressionMixPayload,
	type PetLipSyncLevelPayload,
	type PetLipSyncLevelSource,
	type PetLipSyncProfile,
	type PetLipSyncVisemePayload,
	type PetPlacement,
	type PetRendererStatePayload,
	type PetResolvedEmotionTrigger,
} from "../shared/pet-control";
import {
	normalizeAvatarCommand,
	validateAvatarCommandAgainstCapabilities,
	type AvatarAction,
	type AvatarActionType,
	type AvatarCapabilitySnapshot,
	type AvatarCommand,
	type AvatarCommandResult,
} from "../shared/avatar-command";
import type {
	DesktopPetEventName,
	DesktopPetEventRecord,
} from "../shared/plugin";
import { validatePetControlDirective } from "../shared/pet-control-validator";
import { logger } from "./logger";
import {
	resolveContextMenu,
	resolveDragEnd,
	resolveMouseDown,
	resolveMouseLeave,
	resolveMouseMove,
	resolveMouseUp,
	resolveWheel,
} from "./pet-interaction-controller";
import { PointerMoveCoalescer } from "./pet-pointer-coalescer";
import {
	PetPerformanceController,
	type PetFpsTier,
} from "./pet-performance-controller";
import { resolvePetRenderBudget } from "./pet-render-budget";
import {
	PetEmbodimentCoordinator,
	type PetEmbodimentBehavior,
} from "./pet-embodiment-coordinator";
import {
	resolveCursor,
	resolveMouseCapture,
	resolvePassthroughStrategy,
} from "./pet-interaction-execution";
import { resolveInteractionMode } from "./pet-interaction-mode";
import {
	clamp,
	extractClientPoint,
	extractMouseButton,
	extractScreenPoint,
} from "./pet-interaction-utils";
import { destroyCurrentModel } from "./pet-model-runtime";
import {
	type CompatiblePixiApp,
	createPixiApp,
	getPixiCanvas,
	getReadableError,
	resolveRendererAsset,
} from "./pet-renderer-core";
import {
	getCanvasPointFromClient,
	getInteractionBounds,
	isPointInsideInteractionArea,
} from "./pet-renderer-layout";
import {
	attachWindowListeners,
	detachWindowListeners,
} from "./pet-renderer-runtime";
import {
	computeModelTransform,
	resolveModelAnchor,
} from "./pet-renderer-transform";
import {
	DEFAULT_PET_TEST_STATE,
	type PetTestState,
	syncPetTestState,
} from "./pet-test-state";
import type {
	Live2DAttentionTarget,
	Live2DBehaviorState,
} from "./runtime/live2d-behavior-controller";
import { Live2DRuntimeAdapter } from "./runtime/live2d-runtime-adapter";
import type { VrmRuntimeAdapter as VrmRuntimeAdapterType } from "./runtime/vrm-runtime-adapter";
import type { PetRuntimeAdapter } from "./runtime/pet-runtime-adapter";

type AvatarCancelableActionType = Exclude<AvatarActionType, "cancel">;

interface PetConfig {
	modelType: "live2d" | "vrm";
	modelId: string | null;
	modelPath: string;
	modelManifest: AvatarManifest | null;
	animationPaths: string[];
	scale: number;
	positionX: number | null;
	positionY: number | null;
	placement: PetPlacement;
	clickThrough: boolean;
	locked: boolean;
	lipSyncProfile: PetLipSyncProfile;
}

const DEFAULT_CONFIG: PetConfig = {
	modelType: "live2d",
	modelId: null,
	modelPath: "",
	modelManifest: null,
	animationPaths: [],
	scale: 0.28,
	positionX: null,
	positionY: null,
	placement: "bottom-right",
	clickThrough: true,
	locked: false,
	lipSyncProfile: { ...DEFAULT_PET_CONTROL_STATE.lipSyncProfile },
};

const DEFAULT_SCALE = 0.28;
const MIN_SCALE = 0.12;
const MAX_SCALE = 0.6;
const PASSTHROUGH_MIN_SWITCH_MS = 140;
const HOVER_HYSTERESIS_PX = 14;
const DOUBLE_CLICK_INTERVAL_MS = 280;
const LONG_PRESS_MENU_MS = 560;
const LONG_PRESS_MOVE_CANCEL_PX = 10;
const ACTIVE_FPS = 60;
const IDLE_FPS = 30;
const IDLE_THRESHOLD_MS = 30000;
const MODEL_LOAD_MAX_RETRIES = 3;
const MODEL_LOAD_RETRY_BASE_MS = 250;
const PET_EVENT_DISPATCH_INTERVAL_MS: Record<DesktopPetEventName, number> = {
	onPetClicked: 180,
	onPetDragged: 600,
	onPetIdle: 5000,
	onEmotionChanged: 700,
	onSpeechStart: 0,
	onSpeechEnd: 0,
	onToolStart: 0,
	onToolEnd: 0,
	requestPetAction: 0,
};
const PET_BEHAVIOR_STATES = new Set<Live2DBehaviorState>([
	"idle",
	"thinking",
	"speaking",
	"reacting",
	"sleepy",
	"waiting",
	"curious",
	"focused",
	"interrupted",
]);

const isLive2DBehaviorState = (value: unknown): value is Live2DBehaviorState =>
	typeof value === "string" && PET_BEHAVIOR_STATES.has(value as Live2DBehaviorState);

const isPetRendererDebugEnabled = (): boolean => {
	if (import.meta.env.VITE_PET_RENDERER_DEBUG === "1") {
		return true;
	}
	try {
		return window.localStorage.getItem("yuizaki.pet.debug") === "1";
	} catch {
		return false;
	}
};

const logPetRendererDebug = (...args: unknown[]): void => {
	if (isPetRendererDebugEnabled()) {
		console.info(...args);
	}
};

class PetRenderer {
	private app: CompatiblePixiApp | null = null;
	private canvas: HTMLCanvasElement | null = null;
	private model: Live2DSprite | null = null;
	private live2dViewport: PIXI.Container | null = null;
	private readonly container: HTMLElement;
	private config: PetConfig;
	private destroyed = false;
	private interactMode = false;

	private noticeEl: HTMLDivElement | null = null;
	private quickMenuEl: HTMLDivElement | null = null;
	private mousePassthrough = true;
	private lastPassthroughSwitchAt = 0;
	private passthroughTimer: number | null = null;

	private isDraggingWindow = false;
	private dragMoved = false;
	private dragLastScreen: { x: number; y: number } | null = null;
	private dragLastClient: { x: number; y: number } | null = null;
	private lastMouseClientPoint: { x: number; y: number } | null = null;
	private readonly hoverMoveCoalescer = new PointerMoveCoalescer({
		onMove: (point) => this.processHoverMouseMove(point),
	});
	private mouseDownOnModel = false;
	private modelHovering = false;

	private lastClickAt = 0;
	private singleClickTimer: number | null = null;
	private longPressTimer: number | null = null;
	private longPressOrigin: { x: number; y: number } | null = null;
	private longPressMenuOpen = false;
	private focusedInteraction = false;
	private readonly petEventDispatchAt = new Map<DesktopPetEventName, number>();

	private performanceController: PetPerformanceController | null = null;
	private currentFpsTier: PetFpsTier = "active";
	private readonly renderBudget = resolvePetRenderBudget({
		hardwareConcurrency: navigator.hardwareConcurrency,
		deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory,
	});

	private scalePersistTimer: number | null = null;
	private positionPersistTimer: number | null = null;
	private dragCooldownUntil = 0;
	private readonly testState: PetTestState = { ...DEFAULT_PET_TEST_STATE };
	private vrmRuntime: VrmRuntimeAdapterType | null = null;
	private live2dRuntime: Live2DRuntimeAdapter | null = null;
	private avatarCapabilities: AvatarCapabilitySnapshot | null = null;
	private readonly avatarLastSequences = new Map<string, number>();
	private readonly avatarScheduledCommands = new Map<string, {
		command: AvatarCommand;
		timer: number;
		startAt: number;
	}>();
	private readonly avatarActiveCommands = new Map<string, {
		streamId: string;
		priority: number;
		until: number;
		channels: Set<AvatarCancelableActionType>;
	}>();
	private modelLoadGeneration = 0;
	private modelLoadRetryTimer: number | null = null;
	private modelLoadRetryResolve: ((shouldContinue: boolean) => void) | null = null;
	private companionIdleProfile: PetCompanionIdleProfile = {};
	private externalLipSyncSource: PetLipSyncLevelSource | null = null;
	private readonly embodiment = new PetEmbodimentCoordinator({
		applyBehavior: (behavior) => this.applyResolvedBehavior(behavior),
		resetTransient: (channel) => {
			this.getActiveRuntime()?.executeAvatarAction({ type: "cancel", channel });
		},
	});

	constructor(containerId: string) {
		const element = document.getElementById(containerId);
		if (!element) {
			throw new Error(`Container #${containerId} not found`);
		}

		this.container = element;
		this.config = { ...DEFAULT_CONFIG };
		this.syncTestState();
	}

	async init(): Promise<void> {
		(window as typeof window & { PIXI?: typeof PIXI }).PIXI = PIXI;
		Live2DConfig.MotionGroupIdle = "Idle";
		Live2DConfig.MouseFollow = false;

		this.app = await createPixiApp({
			width: window.innerWidth,
			height: window.innerHeight,
			backgroundAlpha: 0,
			antialias: this.renderBudget.antialias,
			resolution: Math.min(window.devicePixelRatio || 1, this.renderBudget.dprCap),
			autoDensity: true,
			powerPreference: this.renderBudget.powerPreference,
			eventMode: "none",
			eventFeatures: {
				move: false,
				globalMove: false,
				click: false,
				wheel: false,
			},
		});
		this.performanceController = new PetPerformanceController({
			ticker: this.app.ticker,
			isHidden: () => document.hidden,
			onTierChange: (tier, reason) => this.applyFpsTier(tier, reason),
			idleThresholdMs: IDLE_THRESHOLD_MS,
		});

		if ("eventMode" in this.app.stage) {
			(this.app.stage as PIXI.Container & { eventMode?: string }).eventMode =
				"none";
		}

		if ("interactiveChildren" in this.app.stage) {
			(
				this.app.stage as PIXI.Container & { interactiveChildren?: boolean }
			).interactiveChildren = false;
		}

		if (
			"renderer" in this.app &&
			this.app.renderer &&
			"events" in this.app.renderer
		) {
			const events = (
				this.app.renderer as PIXI.Renderer & {
					events?: {
						features?: {
							move?: boolean;
							globalMove?: boolean;
							click?: boolean;
							wheel?: boolean;
						};
					};
				}
			).events;

			if (events?.features) {
				events.features.move = false;
				events.features.globalMove = false;
				events.features.click = false;
				events.features.wheel = false;
			}
		}

		this.canvas = getPixiCanvas(this.app);
		this.canvas.style.width = "100%";
		this.canvas.style.height = "100%";
		this.canvas.style.touchAction = "none";
		this.canvas.style.cursor = "default";
		this.container.appendChild(this.canvas);

		this.setupGlobalListeners();
		this.setupIPCListeners();
		this.showNotice("正在恢复上次桌宠模型...");
		window.live2dApi?.pet.rendererReady();
		this.startPerformanceController();
		this.reportRendererMetrics("init");
	}

	async loadModel(modelPath: string): Promise<void> {
		if (!this.app) {
			return;
		}
		const loadGeneration = this.beginModelLoadGeneration();

		this.avatarCapabilities = null;
		window.live2dApi?.pet.reportAvatarCapabilities(null);
		this.clearAvatarScheduling();
		this.live2dRuntime?.destroy();
		this.vrmRuntime?.destroy();
		this.live2dRuntime = null;
		this.vrmRuntime = null;
		// Publish the teardown boundary immediately so the main process cannot
		// keep advertising the previous model as ready during a replacement.
		this.reportState(true);

		if (this.config.modelType !== "live2d") {
			try {
				const { VrmRuntimeAdapter } = await import("./runtime/vrm-runtime-adapter");
				this.vrmRuntime = new VrmRuntimeAdapter({
					container: this.container,
					config: this.config,
					showNotice: (text) => this.showNotice(text),
					hideNotice: () => this.hideNotice(),
					reportState: (force) => this.reportState(force),
					markActivity: (reason) => this.markActivity(reason),
				});
				const runtime = this.vrmRuntime;
				await this.loadRuntimeWithRecovery(
					() => runtime.loadModel({ modelPath, animationPaths: this.resolveAnimationPaths() }),
					loadGeneration,
					"vrm",
				);
				if (loadGeneration !== this.modelLoadGeneration) {
					return;
				}
				runtime.setCompanionIdleProfile?.(this.companionIdleProfile);
				this.applyRuntimePerformancePolicy();
				this.publishAvatarCapabilities();
				this.reportState(true);
			} catch (error) {
				if (loadGeneration !== this.modelLoadGeneration) {
					return;
				}
				this.reportModelLoadTerminal("vrm", modelPath, error);
				this.showNotice(
					`Failed to load VRM model: ${error instanceof Error ? error.message : String(error)}`,
				);
				console.error("[PetRenderer] failed to load VRM model:", error);
				this.reportState(true);
			}
			return;
		}

		try {
			this.live2dRuntime = new Live2DRuntimeAdapter({
				app: this.app,
				getModel: () => this.model,
				setModel: (model) => {
					this.model = model;
				},
				getViewport: () => this.live2dViewport,
				ensureViewport: () => {
					if (!this.app) {
						throw new Error("Pixi app not initialized");
					}
					if (!this.live2dViewport) {
						this.live2dViewport = new PIXI.Container();
						this.live2dViewport.eventMode = "none";
						this.live2dViewport.interactiveChildren = false;
						this.app.stage.addChild(this.live2dViewport);
					}
					return this.live2dViewport;
				},
				config: this.config,
				showNotice: (text) => this.showNotice(text),
				hideNotice: () => this.hideNotice(),
				installEasyLive2DInteractivity: () =>
					this.installEasyLive2DInteractivity(),
				setupModelInteractivity: () => this.setupModelInteractivity(),
				applyModelTransform: () => this.applyModelTransform(),
				reportState: (force) => this.reportState(force),
				syncMouseCaptureFromLastPoint: (reason, immediate) =>
					this.syncMouseCaptureFromLastPoint(reason, immediate),
				markActivity: (reason) => this.markActivity(reason),
			});
			const runtime = this.live2dRuntime;
			await this.loadRuntimeWithRecovery(
				() => runtime.loadModel({ modelPath, animationPaths: this.resolveAnimationPaths() }),
				loadGeneration,
				"live2d",
			);
			if (loadGeneration !== this.modelLoadGeneration) {
				return;
			}
			this.live2dRuntime.setCompanionIdleProfile(this.companionIdleProfile);
			this.publishAvatarCapabilities();
			console.info("[PetRenderer] model loaded:", modelPath);
		} catch (error) {
			if (loadGeneration !== this.modelLoadGeneration) {
				return;
			}
			this.reportModelLoadTerminal("live2d", modelPath, error);
			this.showNotice(getReadableError(error));
			console.error("[PetRenderer] failed to load model:", error);
			this.reportState(true);
		}
	}

	private async loadRuntimeWithRecovery(
		load: () => Promise<void>,
		generation: number,
		modelType: "live2d" | "vrm",
	): Promise<void> {
		let attempt = 0;
		while (true) {
			if (generation !== this.modelLoadGeneration || this.destroyed) return;
			try {
				await load();
				if (generation === this.modelLoadGeneration) {
					console.info("[PetRenderer] model load recovered", { modelType, attempt });
				}
				return;
			} catch (error) {
				if (generation !== this.modelLoadGeneration || this.destroyed) return;
				if (attempt >= MODEL_LOAD_MAX_RETRIES) throw error;
				attempt += 1;
				const delayMs = MODEL_LOAD_RETRY_BASE_MS * 2 ** (attempt - 1);
				console.warn("[PetRenderer] model load retry scheduled", {
					modelType,
					attempt,
					maxRetries: MODEL_LOAD_MAX_RETRIES,
					delayMs,
					error: error instanceof Error ? error.message : String(error),
				});
				const shouldContinue = await this.waitForModelLoadRetry(delayMs, generation);
				if (!shouldContinue) return;
			}
		}
	}

	private waitForModelLoadRetry(delayMs: number, generation: number): Promise<boolean> {
		return new Promise((resolve) => {
			this.modelLoadRetryResolve = resolve;
			this.modelLoadRetryTimer = window.setTimeout(() => {
				this.modelLoadRetryTimer = null;
				this.modelLoadRetryResolve = null;
				resolve(generation === this.modelLoadGeneration && !this.destroyed);
			}, delayMs);
		});
	}

	private beginModelLoadGeneration(): number {
		this.cancelModelLoadRetry();
		this.modelLoadGeneration += 1;
		return this.modelLoadGeneration;
	}

	private cancelModelLoadRetry(): void {
		if (this.modelLoadRetryTimer !== null) {
			window.clearTimeout(this.modelLoadRetryTimer);
			this.modelLoadRetryTimer = null;
		}
		const resolve = this.modelLoadRetryResolve;
		this.modelLoadRetryResolve = null;
		resolve?.(false);
	}

	private reportModelLoadTerminal(
		modelType: "live2d" | "vrm",
		modelPath: string,
		error: unknown,
	): void {
		console.error("[PetRenderer] model load recovery exhausted", {
			modelType,
			modelPath,
			maxRetries: MODEL_LOAD_MAX_RETRIES,
			error: error instanceof Error ? error.message : String(error),
		});
	}

	private getActiveRuntime(): PetRuntimeAdapter | null {
		return this.config.modelType === "vrm" ? this.vrmRuntime : this.live2dRuntime;
	}

	private resolveAnimationPaths(): string[] {
		return this.config.animationPaths
			.map((animationPath) => animationPath.trim())
			.filter(Boolean)
			.map((animationPath) => /^https?:\/\//i.test(animationPath)
				|| animationPath.startsWith("file:")
				|| animationPath.startsWith("/api/")
				? animationPath
				: resolveRendererAsset(animationPath));
	}

	private publishAvatarCapabilities(): void {
		const runtime = this.getActiveRuntime();
		if (!runtime) return;
		this.avatarCapabilities = runtime.getCapabilities();
		window.live2dApi?.pet.reportAvatarCapabilities(this.avatarCapabilities);
	}

	private reportAvatarCommandResult(result: AvatarCommandResult): void {
		window.live2dApi?.pet.reportAvatarCommandResult(result);
	}

	private executeAvatarCommand(data: unknown): void {
		const input = data as AvatarCommand;
		const now = Date.now();
		const normalized = normalizeAvatarCommand(input, now);
		if (!normalized.command) {
			this.reportAvatarCommandResult({
				commandId: typeof input?.id === "string" ? input.id : "unknown",
				sequence: Number.isInteger(input?.sequence) ? input.sequence : -1,
				status: normalized.status,
				message: normalized.errors.join("; "),
				at: now,
			});
			return;
		}

		const command = normalized.command;
		const lastSequence = this.avatarLastSequences.get(command.streamId) ?? -1;
		if (command.sequence <= lastSequence) {
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "dropped",
				message: "Avatar command sequence is stale",
				at: now,
			});
			return;
		}

		const runtime = this.getActiveRuntime();
		const capabilities = this.avatarCapabilities ?? runtime?.getCapabilities() ?? null;
		if (!runtime || !capabilities) {
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "rejected",
				message: "Pet model is not ready",
				at: now,
			});
			return;
		}

		const capabilityResult = validateAvatarCommandAgainstCapabilities(command, capabilities);
		if (capabilityResult.status === "rejected") {
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "rejected",
				capabilityRevision: capabilities.revision,
				message: capabilityResult.message,
				at: now,
			});
			return;
		}
		this.pruneAvatarCommands(now);
		const activePriority = Math.max(
			0,
			...Array.from(this.avatarActiveCommands.values())
				.filter((active) => active.until > now)
				.map((active) => active.priority),
		);
		if (command.interrupt === "ignore" && command.priority <= activePriority) {
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "dropped",
				capabilityRevision: capabilities.revision,
				message: "Lower-priority avatar command ignored",
				at: now,
			});
			return;
		}

		this.avatarLastSequences.set(command.streamId, command.sequence);
		if (command.interrupt === "replace") {
			this.cancelAvatarCommands(runtime);
		}

		const startAt = Math.max(now, command.startAt ?? now);
		if (command.expiresAt !== undefined && startAt > command.expiresAt) {
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "dropped",
				capabilityRevision: capabilities.revision,
				message: "Avatar command expired before its scheduled start",
				at: now,
			});
			return;
		}
		const queueStart = command.interrupt === "queue"
			? Math.max(startAt, this.avatarQueueTail(command.streamId))
			: startAt;
		const durationMs = this.avatarCommandDuration(command);
		this.avatarLastSequences.set(command.streamId, command.sequence);
		this.avatarQueueTailByStream.set(command.streamId, queueStart + durationMs);
		if (queueStart > now) {
			const timer = window.setTimeout(() => {
				this.avatarScheduledCommands.delete(command.id);
				if (command.expiresAt !== undefined && Date.now() > command.expiresAt) {
					this.reportAvatarCommandResult({
						commandId: command.id,
						sequence: command.sequence,
						status: "dropped",
						message: "Avatar command delivery lease expired before execution",
						at: Date.now(),
					});
					return;
				}
				this.runAvatarCommand(command, runtime, capabilities, capabilityResult);
			}, queueStart - now);
			this.avatarScheduledCommands.set(command.id, { command, timer, startAt: queueStart });
			this.reportAvatarCommandResult({
				commandId: command.id,
				sequence: command.sequence,
				status: "accepted",
				capabilityRevision: capabilities.revision,
				at: now,
			});
			return;
		}
		this.runAvatarCommand(command, runtime, capabilities, capabilityResult);
	}

	private readonly avatarQueueTailByStream = new Map<string, number>();

	private avatarQueueTail(streamId: string): number {
		return this.avatarQueueTailByStream.get(streamId) ?? Date.now();
	}

	private avatarCommandDuration(command: AvatarCommand): number {
		return Math.max(16, ...command.actions.map((action) => {
			switch (action.type) {
				case "behavior": return action.durationMs ?? 800;
				case "affect": return action.decayMs ?? 1200;
				case "gaze": return action.holdMs ?? 800;
				case "expression": return (action.fadeInMs ?? 160) + (action.fadeOutMs ?? 1200);
				case "parameterPatch": return action.durationMs ?? 600;
				case "motion": return 1000;
				case "viseme": return 120;
				case "cancel": return 16;
			}
		}));
	}

	private runAvatarCommand(
		command: AvatarCommand,
		runtime: PetRuntimeAdapter,
		capabilities: AvatarCapabilitySnapshot,
		capabilityResult: ReturnType<typeof validateAvatarCommandAgainstCapabilities>,
	): void {
		let degraded = capabilityResult.status === "degraded";
		const unsupported = new Set(capabilityResult.unsupportedActionIndexes);
		const channels = new Set<AvatarCancelableActionType>();
		const messages: string[] = [];
		command.actions.forEach((action, index) => {
			if (unsupported.has(index)) {
				degraded = true;
				return;
			}
			if (action.type === "cancel") {
				this.cancelAvatarTarget(action, runtime);
				return;
			}
			channels.add(action.type);
			if (action.type === "behavior") {
				this.embodiment.requestBehavior(this.mapAvatarBehavior(action.behavior), action.durationMs ?? 0, command.id);
				return;
			}
			if (action.type === "gaze") {
				this.embodiment.beginTransient("gaze", action.holdMs ?? 800, command.id);
			} else if (action.type === "expression") {
				this.embodiment.beginTransient("expression", (action.fadeInMs ?? 160) + (action.fadeOutMs ?? 1200), command.id);
			} else if (action.type === "affect") {
				this.embodiment.beginTransient("expression", action.decayMs ?? 1200, command.id);
			} else if (action.type === "viseme") {
				if (action.active === false) this.embodiment.cancelOwner(command.id, "viseme");
				else this.embodiment.beginTransient("viseme", 120, command.id);
			}
			const result = runtime.executeAvatarAction(action);
			if (result.status !== "completed") {
				degraded = true;
				if (result.message) messages.push(result.message);
			}
		});
		this.avatarActiveCommands.set(command.id, {
			streamId: command.streamId,
			priority: command.priority,
			until: Date.now() + this.avatarCommandDuration(command),
			channels,
		});
		this.reportAvatarCommandResult({
			commandId: command.id,
			sequence: command.sequence,
			status: degraded ? "degraded" : "accepted",
			modelType: runtime.modelType,
			capabilityRevision: capabilities.revision,
			...(capabilityResult.unsupportedActionIndexes.length > 0
				? { unsupportedActionIndexes: capabilityResult.unsupportedActionIndexes }
				: {}),
			...(messages.length > 0 ? { message: messages.join("; ") } : {}),
			at: Date.now(),
		});
	}

	private pruneAvatarCommands(now: number): void {
		for (const [commandId, active] of this.avatarActiveCommands) {
			if (active.until <= now) this.avatarActiveCommands.delete(commandId);
		}
		for (const [streamId, tail] of this.avatarQueueTailByStream) {
			if (tail <= now) this.avatarQueueTailByStream.delete(streamId);
		}
	}

	private cancelAvatarCommands(runtime: PetRuntimeAdapter): void {
		this.clearAvatarScheduling();
		runtime.executeAvatarAction({ type: "cancel" });
		this.embodiment.refresh();
	}

	private clearAvatarScheduling(): void {
		for (const scheduled of this.avatarScheduledCommands.values()) {
			window.clearTimeout(scheduled.timer);
		}
		this.avatarScheduledCommands.clear();
		this.avatarActiveCommands.clear();
		this.avatarQueueTailByStream.clear();
		this.embodiment.cancelCommandClaims();
	}

	private cancelAvatarTarget(action: Extract<AvatarAction, { type: "cancel" }>, runtime: PetRuntimeAdapter): void {
		if (action.commandId) {
			const scheduled = this.avatarScheduledCommands.get(action.commandId);
			if (scheduled) {
				window.clearTimeout(scheduled.timer);
				this.avatarScheduledCommands.delete(action.commandId);
			}
			const active = this.avatarActiveCommands.get(action.commandId);
			if (active) {
				let channels: AvatarCancelableActionType[];
				if (!action.channel) {
					channels = [...active.channels];
				} else if (active.channels.has(action.channel)) {
					channels = [action.channel];
				} else {
					channels = [];
				}
				for (const channel of channels) {
					runtime.executeAvatarAction({ type: "cancel", channel });
				}
				if (!action.channel) this.avatarActiveCommands.delete(action.commandId);
				else active.channels.delete(action.channel);
			}
			const embodimentChannel = this.mapEmbodimentChannel(action.channel);
			if (!action.channel) this.embodiment.cancelOwner(action.commandId);
			else if (embodimentChannel) this.embodiment.cancelOwner(action.commandId, embodimentChannel);
			return;
		}
		const embodimentChannel = this.mapEmbodimentChannel(action.channel);
		if (!action.channel) this.embodiment.cancelCommandClaims();
		else if (embodimentChannel) this.embodiment.cancelCommandClaims(embodimentChannel);
		runtime.executeAvatarAction(action);
		this.embodiment.refresh();
	}

	private mapEmbodimentChannel(channel: AvatarActionType | undefined): "behavior" | "expression" | "gaze" | "viseme" | undefined {
		if (channel === "affect" || channel === "expression") return "expression";
		if (channel === "behavior" || channel === "gaze" || channel === "viseme") return channel;
		return undefined;
	}

	playMotion(group: string, index = 0): void {
		if (this.config.modelType !== "live2d") {
			return;
		}

		this.live2dRuntime?.triggerMotion?.(group, index);
		this.testState.lastMotionGroup = group;
		this.testState.lastMotionIndex = index;
		this.syncTestState();
		this.markActivity(`motion:${group}`);
	}

	playRandomMotion(): void {
		if (this.config.modelType !== "live2d") {
			return;
		}

		this.live2dRuntime?.triggerRandomMotion?.();
		const groups = ["Idle", "Tap", "Tap@Body", "Flick", "Flick@Body"];
		const group = groups[Math.floor(Math.random() * groups.length)];
		this.testState.lastMotionGroup = group;
		this.testState.lastMotionIndex = null;
		this.syncTestState();
		this.markActivity(`motion:${group}`);
	}

	setExpression(name: string): void {
		if (this.config.modelType !== "live2d") {
			return;
		}

		this.live2dRuntime?.triggerExpression?.(name);
		this.testState.lastExpressionName = name;
		this.syncTestState();
		this.markActivity(`expression:${name}`);
	}

	setExpressionMix(payload: PetExpressionMixPayload): void {
		this.applyPetControlDirective({
			expressionMix: payload.expressions ?? [],
			parameterOverrides: payload.parameterOverrides ?? [],
			...(payload.motion ? { motion: payload.motion } : {}),
			intensity: payload.intensity ?? 1,
			durationMs: payload.durationMs ?? 1800,
		});
	}

	applyPetControlDirective(directive: PetControlDirective): void {
		if (this.config.modelType !== "live2d") {
			return;
		}

		const normalizedDirective = this.config.modelManifest
			? this.normalizePetControlDirective(directive)
			: directive;

		if (normalizedDirective.motion) {
			this.live2dRuntime?.triggerMotion?.(
				normalizedDirective.motion.group,
				normalizedDirective.motion.index,
			);
			this.testState.lastMotionGroup = normalizedDirective.motion.group;
			this.testState.lastMotionIndex = normalizedDirective.motion.index;
		}

		const normalizedPayload: PetExpressionMixPayload = {
			expressions: normalizedDirective.expressionMix,
			parameterOverrides: normalizedDirective.parameterOverrides,
			intensity: normalizedDirective.intensity,
			durationMs: normalizedDirective.durationMs,
		};
		this.live2dRuntime?.triggerExpressionMix?.(normalizedPayload);
		const primary = normalizedPayload.expressions?.[0]?.expression ?? null;
		if (primary) {
			this.testState.lastExpressionName = primary;
		}
		if (primary || normalizedDirective.motion) {
			this.syncTestState();
		}
		this.markActivity("pet-control-directive");
	}

	private normalizePetControlDirective(
		directive: PetControlDirective,
	): PetControlDirective {
		if (!this.config.modelManifest) {
			return directive;
		}
		const validation = validatePetControlDirective(
			directive,
			this.config.modelManifest,
		);
		if (!validation.valid || validation.warnings.length > 0) {
			console.debug("[PetRenderer] pet_control validation", {
				errors: validation.errors,
				warnings: validation.warnings,
				fallbackExpression: validation.fallbackExpression,
			});
		}
		return validation.directive;
	}

	triggerEmotion(trigger: PetResolvedEmotionTrigger): void {
		if (this.config.modelType === "live2d") {
			this.live2dRuntime?.triggerEmotion(trigger);
			if (trigger.expressionName) {
				this.testState.lastExpressionName = trigger.expressionName;
			}
			if (trigger.motion) {
				this.testState.lastMotionGroup = trigger.motion.group;
				this.testState.lastMotionIndex = trigger.motion.index;
			}
			this.syncTestState();
		}
	}

	setBehaviorState(state: Live2DBehaviorState, durationMs = 0): void {
		this.embodiment.requestBehavior(state, durationMs);
		this.emitPetEvent("onEmotionChanged", {
			state,
			durationMs,
			source: "renderer",
		});
	}

	private applyResolvedBehavior(state: PetEmbodimentBehavior): void {
		if (this.config.modelType === "live2d") {
			this.live2dRuntime?.setBehaviorState(state);
			return;
		}
		let behavior: Extract<AvatarAction, { type: "behavior" }>['behavior'];
		switch (state) {
			case "speaking":
				behavior = "speak";
				break;
			case "thinking":
			case "focused":
				behavior = "think";
				break;
			case "reacting":
			case "interrupted":
				behavior = "react";
				break;
			case "curious":
				behavior = "backchannel";
				break;
			case "waiting":
				behavior = "listen";
				break;
			default:
				behavior = "idle";
		}
		this.vrmRuntime?.executeAvatarAction({ type: "behavior", behavior });
	}

	private mapAvatarBehavior(behavior: Extract<AvatarAction, { type: "behavior" }>['behavior']): PetEmbodimentBehavior {
		switch (behavior) {
			case "listen": return "focused";
			case "think": return "thinking";
			case "speak": return "speaking";
			case "backchannel": return "curious";
			case "react": return "reacting";
			case "idle": return "idle";
		}
	}

	setCompanionIdleProfile(profile: PetCompanionIdleProfile): void {
		this.companionIdleProfile = { ...profile };
		this.live2dRuntime?.setCompanionIdleProfile(profile);
		this.vrmRuntime?.setCompanionIdleProfile?.(profile);
	}

	private setAttentionFromClientPoint(
		clientPoint: { x: number; y: number } | null,
		strength: number,
		durationMs: number,
	): void {
		if (!clientPoint) {
			return;
		}

		const width = Math.max(1, window.innerWidth);
		const height = Math.max(1, window.innerHeight);
		const target: Live2DAttentionTarget = {
			x: clamp((clientPoint.x / width) * 2 - 1, -1, 1),
			y: clamp(1 - (clientPoint.y / height) * 2, -1, 1),
			strength: clamp(strength, 0, 1),
			durationMs,
		};
		this.live2dRuntime?.setAttentionTarget(target);
		this.vrmRuntime?.setAttentionTarget(target);
	}

	async startLipSync(audioUrl: string, requestId?: string): Promise<void> {
		if (this.config.modelType !== "live2d" || !audioUrl.trim()) {
			if (requestId) {
				window.live2dApi?.pet.reportLipSyncReady?.({ requestId, ready: false });
			}
			return;
		}
		let readyReported = false;
		let speechStarted = false;
		const announceSpeechStart = () => {
			if (speechStarted) return;
			speechStarted = true;
			this.emitPetEvent("onSpeechStart", { audioUrl });
			this.markActivity("tts-lipsync-start");
		};
		const reportReady = (ready: boolean) => {
			if (!requestId || readyReported) return;
			readyReported = true;
			window.live2dApi?.pet.reportLipSyncReady?.({ requestId, ready });
		};
		const runtime = this.live2dRuntime;
		if (!runtime) {
			reportReady(false);
			return;
		}
		// Speech start is the request boundary. The analyzer may still be
		// loading/resuming, but the panel must be able to align its audio clock
		// without waiting for an HTMLAudioElement promise to settle.
		announceSpeechStart();
		this.embodiment.requestBehavior("speaking");
		try {
			await runtime.startLipSync(audioUrl, () => reportReady(true));
		} finally {
			// A failed or interrupted analyzer still needs to release the main
			// process waiter; the request boundary was already announced above.
			reportReady(true);
		}
	}

	stopLipSync(options: { interrupted?: boolean } = {}): void {
		this.live2dRuntime?.stopLipSync();
		this.embodiment.clearBehavior("speaking");
		this.setBehaviorState(options.interrupted ? "interrupted" : "waiting", 900);
		this.emitPetEvent("onSpeechEnd", {
			interrupted: options.interrupted === true,
		});
		this.markActivity("tts-lipsync-stop");
	}

	setExternalLipSync(payload: PetLipSyncLevelPayload): void {
		const active = payload.active === true;
		const level = active ? clamp(Number(payload.level) || 0, 0, 1) : 0;
		if (
			!active &&
			this.externalLipSyncSource !== null &&
			this.externalLipSyncSource !== payload.source
		) {
			return;
		}

		this.live2dRuntime?.setLipSyncLevel(level, active);
		this.vrmRuntime?.setLipSyncLevel(level, active);
		if (active) {
			this.embodiment.requestBehavior("speaking");
		} else {
			this.embodiment.clearBehavior("speaking");
		}

		if (active && this.externalLipSyncSource !== payload.source) {
			if (this.externalLipSyncSource !== null) {
				this.emitPetEvent("onSpeechEnd", {
					interrupted: true,
					source: this.externalLipSyncSource,
				});
			}
			this.externalLipSyncSource = payload.source;
			this.emitPetEvent("onSpeechStart", { source: payload.source });
			this.markActivity(`${payload.source}-lipsync-start`);
		} else if (!active && this.externalLipSyncSource === payload.source) {
			this.externalLipSyncSource = null;
			this.emitPetEvent("onSpeechEnd", {
				interrupted: false,
				source: payload.source,
			});
			this.markActivity(`${payload.source}-lipsync-stop`);
		}
	}

	setExternalViseme(payload: PetLipSyncVisemePayload): void {
		if (payload.active) {
			this.embodiment.beginTransient("viseme");
		} else {
			this.embodiment.endTransient("viseme");
		}
		this.vrmRuntime?.setLipSyncViseme(
			payload.viseme,
			clamp(Number(payload.weight) || 0, 0, 1),
			payload.active === true,
		);
		this.live2dRuntime?.setLipSyncViseme(
			payload.viseme,
			clamp(Number(payload.weight) || 0, 0, 1),
			payload.active === true,
		);
	}

	setScale(scale: number, report = true): void {
		this.config.scale = clamp(scale, MIN_SCALE, MAX_SCALE);
		this.applyModelTransform();

		if (report) {
			this.reportState(true);
		}
	}

	private applyConfig(patch: PetControlConfigPatch, report = true): void {
		let nextModelPath: string | null = null;
		const previousModelType = this.config.modelType;
		const previousModelId = this.config.modelId;
		if (patch.modelType === "live2d" || patch.modelType === "vrm") {
			this.config.modelType = patch.modelType;
		}

		if (typeof patch.modelId === "string" || patch.modelId === null) {
			this.config.modelId = patch.modelId;
		}

		if (
			typeof patch.modelPath === "string" &&
			patch.modelPath.trim().length > 0
		) {
			const resolvedModelPath =
				/^https?:\/\//i.test(patch.modelPath) ||
				patch.modelPath.startsWith("file:")
					? patch.modelPath
					: resolveRendererAsset(patch.modelPath);

			if (resolvedModelPath !== this.config.modelPath) {
				this.config.modelPath = resolvedModelPath;
				nextModelPath = resolvedModelPath;
			}
		}

		const modelIdentityChanged = previousModelType !== this.config.modelType || previousModelId !== this.config.modelId;
		if (modelIdentityChanged) {
			this.avatarCapabilities = null;
			window.live2dApi?.pet.reportAvatarCapabilities(null);
			if (!nextModelPath && this.config.modelPath) {
				nextModelPath = this.config.modelPath;
			}
		}

		if (typeof patch.scale === "number" && Number.isFinite(patch.scale)) {
			this.config.scale = clamp(patch.scale, MIN_SCALE, MAX_SCALE);
		}

		if (typeof patch.interactMode === "boolean") {
			this.interactMode = patch.interactMode;
		}

		if (typeof patch.clickThrough === "boolean") {
			this.config.clickThrough = patch.clickThrough;
			if (this.config.clickThrough) {
				this.finishWindowDrag();
				this.requestMousePassthrough(true, "click-through-config", true);
			}
		}

		if (patch.modelManifest !== undefined) {
			this.config.modelManifest = patch.modelManifest ?? null;
		}
		if (Array.isArray(patch.animationPaths)) {
			this.config.animationPaths = patch.animationPaths
				.filter((animationPath): animationPath is string => typeof animationPath === "string")
				.map((animationPath) => animationPath.trim())
				.filter(Boolean);
		}

		if (patch.lipSyncProfile) {
			this.config.lipSyncProfile = normalizePetLipSyncProfile(
				patch.lipSyncProfile,
				this.config.lipSyncProfile,
			);
		}

		if (typeof patch.locked === "boolean") {
			this.config.locked = patch.locked;
			if (this.config.locked) {
				this.finishWindowDrag();
				this.requestMousePassthrough(false, "locked-state", true);
			}
		}

		if (typeof patch.opacity === "number" && Number.isFinite(patch.opacity)) {
			document.body.style.opacity = `${clamp(patch.opacity, 0.1, 1)}`;
		}

		if (
			patch.placement === "bottom-right" ||
			patch.placement === "bottom-left" ||
			patch.placement === "top-right" ||
			patch.placement === "top-left" ||
			patch.placement === "center" ||
			patch.placement === "free"
		) {
			this.config.placement = patch.placement;
		}

		if (typeof patch.positionX === "number") {
			this.config.positionX = patch.positionX;
		} else if (patch.positionX === null) {
			this.config.positionX = null;
		}

		if (typeof patch.positionY === "number") {
			this.config.positionY = patch.positionY;
		} else if (patch.positionY === null) {
			this.config.positionY = null;
		}

		if (nextModelPath) {
			void this.loadModel(nextModelPath);
			return;
		}

		this.live2dRuntime?.applyConfig({
			modelManifest: this.config.modelManifest,
			lipSyncProfile: this.config.lipSyncProfile,
		});
		this.vrmRuntime?.applyConfig({
			lipSyncProfile: this.config.lipSyncProfile,
		});
		if (modelIdentityChanged) {
			this.publishAvatarCapabilities();
		}
		this.applyModelTransform();

		if (report) {
			this.reportState(true);
		}
	}

	private applyModelTransform(): void {
		if (this.config.modelType === "vrm") {
			this.vrmRuntime?.applyConfig({
				modelType: this.config.modelType,
				modelId: this.config.modelId,
				modelPath: this.config.modelPath,
				scale: this.config.scale,
				positionX: this.config.positionX,
				positionY: this.config.positionY,
				placement: this.config.placement,
				lipSyncProfile: this.config.lipSyncProfile,
			});
			this.testState.interactionBounds = null;
			this.syncTestState();
			this.reportRendererMetrics("transform-vrm");
			return;
		}

		if (!this.model || !this.app) {
			return;
		}

		if (!this.live2dViewport) {
			this.live2dViewport = new PIXI.Container();
			this.live2dViewport.eventMode = "none";
			this.live2dViewport.interactiveChildren = false;
			this.app.stage.addChild(this.live2dViewport);
		}

		const viewportWidth = window.innerWidth;
		const viewportHeight = window.innerHeight;

		const transform = computeModelTransform({
			configScale: this.config.scale,
			defaultScale: DEFAULT_SCALE,
			minScale: MIN_SCALE,
			maxScale: MAX_SCALE,
			baseScale: 1,
			viewportWidth,
			viewportHeight,
			positionX: this.config.positionX,
			positionY: this.config.positionY,
			placement: this.config.placement,
		});

		this.live2dViewport.position.set(transform.anchorX, transform.anchorY);
		this.live2dViewport.scale.set(transform.nextScale);
		this.model.position.set(0, 0);
		const placementAdjustment = this.resolveVisualPlacementAdjustment(
			viewportWidth,
			viewportHeight,
		);
		if (placementAdjustment.x !== 0 || placementAdjustment.y !== 0) {
			this.live2dViewport.position.set(
				transform.anchorX + placementAdjustment.x,
				transform.anchorY + placementAdjustment.y,
			);
		}
		const interactionBounds = {
			...transform.interactionBounds,
			x: transform.interactionBounds.x + placementAdjustment.x,
			y: transform.interactionBounds.y + placementAdjustment.y,
		};

		const modelCanvasSize =
			"getModelCanvasSize" in this.model &&
			typeof this.model.getModelCanvasSize === "function"
				? this.model.getModelCanvasSize()
				: null;
		const localBounds =
			"getLocalBounds" in this.model &&
			typeof this.model.getLocalBounds === "function"
				? this.model.getLocalBounds()
				: null;

		logPetRendererDebug("[PetRenderer][transform] model geometry", {
			configScale: this.config.scale,
			baseScale: 1,
			nextScale: transform.nextScale,
			anchorX: transform.anchorX,
			anchorY: transform.anchorY,
			modelCanvasSize,
			localBounds,
			position: {
				x: this.live2dViewport.position.x,
				y: this.live2dViewport.position.y,
			},
			scale: {
				x: this.live2dViewport.scale.x,
				y: this.live2dViewport.scale.y,
			},
			anchor: {
				x: "anchor" in this.model ? this.model.anchor?.x : undefined,
				y: "anchor" in this.model ? this.model.anchor?.y : undefined,
			},
		});

		this.testState.interactionBounds = interactionBounds;
		this.syncTestState();

		this.reportRendererMetrics("transform");
		this.syncMouseCaptureFromLastPoint("transform");
	}

	private buildStatePayload(): PetRendererStatePayload {
		return {
			modelType: this.config.modelType,
			modelId: this.config.modelId,
			scale: this.config.scale,
			positionX:
				typeof this.config.positionX === "number" ? this.config.positionX : null,
			positionY:
				typeof this.config.positionY === "number" ? this.config.positionY : null,
			placement: this.config.placement,
			clickThrough: this.config.clickThrough,
			locked: this.config.locked,
			ready:
				this.config.modelType === "vrm"
					? Boolean(this.vrmRuntime)
					: Boolean(this.model),
		};
	}

	private resolveVisualPlacementAdjustment(
		viewportWidth: number,
		viewportHeight: number,
	): { x: number; y: number } {
		if (!this.live2dViewport || this.config.placement === "free") {
			return { x: 0, y: 0 };
		}

		const bounds = this.live2dViewport.getBounds();
		if (
			!Number.isFinite(bounds.x) ||
			!Number.isFinite(bounds.y) ||
			!Number.isFinite(bounds.width) ||
			!Number.isFinite(bounds.height) ||
			bounds.width <= 0 ||
			bounds.height <= 0
		) {
			return { x: 0, y: 0 };
		}

		const margin = Math.min(
			32,
			Math.max(12, Math.min(viewportWidth, viewportHeight) * 0.04),
		);
		const left = bounds.x;
		const top = bounds.y;
		const right = bounds.x + bounds.width;
		const bottom = bounds.y + bounds.height;
		const centerX = bounds.x + bounds.width / 2;
		const centerY = bounds.y + bounds.height / 2;
		const adjustment = { x: 0, y: 0 };

		if (this.config.placement === "bottom-right") {
			adjustment.x = viewportWidth - margin - right;
			adjustment.y = viewportHeight - margin - bottom;
		} else if (this.config.placement === "bottom-left") {
			adjustment.x = margin - left;
			adjustment.y = viewportHeight - margin - bottom;
		} else if (this.config.placement === "top-right") {
			adjustment.x = viewportWidth - margin - right;
			adjustment.y = margin - top;
		} else if (this.config.placement === "top-left") {
			adjustment.x = margin - left;
			adjustment.y = margin - top;
		} else if (this.config.placement === "center") {
			adjustment.x = viewportWidth / 2 - centerX;
			adjustment.y = viewportHeight / 2 - centerY;
		}

		return adjustment;
	}

	private reportState(force = false): void {
		if (!force && !this.model) {
			return;
		}

		window.live2dApi?.pet.reportState(this.buildStatePayload());
	}

	private setupGlobalListeners(): void {
		attachWindowListeners({
			handleWindowMouseDown: this.handleWindowMouseDown,
			handleWindowMouseMove: this.handleWindowMouseMove,
			handleWindowMouseUp: this.handleWindowMouseUp,
			handleWindowMouseLeave: this.handleWindowMouseLeave,
			handleWindowWheel: this.handleWindowWheel,
			handleResize: this.handleResize,
			handleWindowContextMenu: this.handleWindowContextMenu,
			handleWindowError: this.handleWindowError,
			handleUnhandledRejection: this.handleUnhandledRejection,
		});
		document.addEventListener('visibilitychange', this.handleVisibilityChange);
	}

	private installEasyLive2DInteractivity(): void {
		if (!this.model) {
			return;
		}

		this.model.onLive2D("ready", () => {
			this.hideNotice();
			this.reportState(true);
		});

		this.model.onLive2D("hit", ({ hitAreaName }: { hitAreaName: string }) => {
			this.testState.lastHitAreaName = hitAreaName;
			this.syncTestState();
			this.modelHovering = true;
			this.requestMousePassthrough(false, `hit:${hitAreaName}`, true);
			this.updateCursor(true);
			this.setAttentionFromClientPoint(this.lastMouseClientPoint, 0.72, 1500);
			this.markActivity(`hit:${hitAreaName}`);
		});
	}

	private setupModelInteractivity(): void {
		if (!this.model) {
			return;
		}

		const safeHitTest = (event: Event): boolean => {
			const clientPoint = extractClientPoint(event);
			if (!clientPoint) {
				return false;
			}
			const canvasPoint = this.getCanvasPointFromClient(
				clientPoint.x,
				clientPoint.y,
			);
			if (!canvasPoint) {
				return false;
			}
			return this.isPointInsideInteractionArea(canvasPoint.x, canvasPoint.y, 4);
		};

		this.canvas?.addEventListener("pointerdown", (event: PointerEvent) => {
			if (this.config.clickThrough) {
				return;
			}

			const hit = safeHitTest(event);
			this.testState.lastPointerDownAt = Date.now();
			this.testState.lastPointerDownHit = hit;
			this.syncTestState();

			if (!hit) {
				return;
			}

			const button = extractMouseButton(event);
			if (button !== 0) {
				return;
			}

			const clientPoint = extractClientPoint(event);
			if (clientPoint) {
				this.lastMouseClientPoint = clientPoint;
			}

			this.mouseDownOnModel = true;
			this.dragMoved = false;
			this.modelHovering = true;
			this.setAttentionFromClientPoint(clientPoint, 0.9, 1700);
			this.setBehaviorState("curious", 1400);
			if (clientPoint) {
				this.scheduleLongPressMenu(clientPoint);
			}
			this.markActivity("model-mousedown");
			this.requestMousePassthrough(false, "model-mousedown", true);

			if (this.config.locked) {
				event.stopPropagation?.();
				event.preventDefault?.();
				return;
			}

			const fallbackClientPoint = clientPoint ?? {
				x: event.clientX ?? 0,
				y: event.clientY ?? 0,
			};
			const screenPoint = extractScreenPoint(event) ?? {
				x: fallbackClientPoint.x,
				y: fallbackClientPoint.y,
			};

			this.isDraggingWindow = true;
			this.dragLastScreen = screenPoint;
			this.dragLastClient = fallbackClientPoint;
			this.testState.lastDragStartAt = Date.now();
			this.syncTestState();
			this.requestMousePassthrough(false, "drag-lock", true);
			this.canvas?.setPointerCapture?.(event.pointerId);
			this.updateCursor(true);

			event.stopPropagation?.();
			event.preventDefault?.();
		});

		this.canvas?.addEventListener("contextmenu", (event: MouseEvent) => {
			if (this.config.clickThrough) {
				return;
			}

			if (!safeHitTest(event)) {
				return;
			}

			const clientPoint = extractClientPoint(event);
			if (clientPoint) {
				this.lastMouseClientPoint = clientPoint;
			}

			this.setAttentionFromClientPoint(clientPoint, 0.82, 1600);
			this.setBehaviorState("waiting", 2200);
			this.requestMousePassthrough(false, "model-rightdown", true);
			this.testState.lastRightClickTriggeredAt = Date.now();
			this.syncTestState();
			this.showQuickMenu(event.clientX ?? 0, event.clientY ?? 0);
			this.emitPetEvent("onPetClicked", {
				gesture: "context_menu",
				x: Math.round(event.clientX ?? 0),
				y: Math.round(event.clientY ?? 0),
			});
			this.markActivity("model-right-click-menu");
			event.stopPropagation?.();
			event.preventDefault?.();
		});

		this.canvas?.addEventListener("pointermove", (event: PointerEvent) => {
			if (this.config.clickThrough) {
				return;
			}

			if (!this.isDraggingWindow) {
				return;
			}
			this.handleWindowMouseMove(event as unknown as MouseEvent);
		});

		this.canvas?.addEventListener("pointerup", (event: PointerEvent) => {
			if (this.config.clickThrough) {
				return;
			}

			this.canvas?.releasePointerCapture?.(event.pointerId);
			this.handleWindowMouseUp(event as unknown as MouseEvent);
		});
	}

	private getInteractionBounds(buffer = 0): PIXI.Rectangle | null {
		return getInteractionBounds(this.testState.interactionBounds, buffer);
	}

	private isPointInsideInteractionArea(
		x: number,
		y: number,
		buffer = 0,
	): boolean {
		return isPointInsideInteractionArea({
			model: this.model,
			x,
			y,
			bounds: this.getInteractionBounds(buffer),
		});
	}

	private getCanvasPointFromClient(
		clientX: number,
		clientY: number,
	): { x: number; y: number } | null {
		return getCanvasPointFromClient({
			canvas: this.canvas,
			app: this.app,
			clientX,
			clientY,
		});
	}

	private requestMousePassthrough(
		ignore: boolean,
		_reason: string,
		immediate = false,
	): void {
		if (this.config.clickThrough) {
			ignore = true;
		}

		const strategy = resolvePassthroughStrategy({
			now: Date.now(),
			dragCooldownUntil: this.dragCooldownUntil,
			mousePassthrough: this.mousePassthrough,
			lastPassthroughSwitchAt: this.lastPassthroughSwitchAt,
			minSwitchMs: PASSTHROUGH_MIN_SWITCH_MS,
			immediate,
			ignore,
		});

		if (strategy.shouldSkip) {
			return;
		}

		const apply = () => {
			this.mousePassthrough = ignore;
			this.lastPassthroughSwitchAt = Date.now();
			window.live2dApi?.pet.setMouseIgnore(ignore, ignore);
		};

		if (this.passthroughTimer !== null) {
			window.clearTimeout(this.passthroughTimer);
			this.passthroughTimer = null;
		}

		if (strategy.shouldApplyImmediately) {
			apply();
			return;
		}

		this.passthroughTimer = window.setTimeout(() => {
			this.passthroughTimer = null;
			apply();
		}, strategy.delayMs);
	}

	private syncMouseCaptureFromPoint(
		clientX: number,
		clientY: number,
		reason: string,
	): void {
		if (this.config.clickThrough) {
			this.modelHovering = false;
			this.requestMousePassthrough(true, reason, true);
			this.updateCursor(false);
			return;
		}

		const point = this.getCanvasPointFromClient(clientX, clientY);
		if (!point) {
			return;
		}

		const buffer = this.mousePassthrough
			? 0
			: Math.round(HOVER_HYSTERESIS_PX * 0.5);
		const hovering = this.isPointInsideInteractionArea(
			point.x,
			point.y,
			buffer,
		);
		this.applyMouseCaptureDecision(hovering, reason);
	}

	private applyMouseCaptureDecision(
		hovering: boolean,
		reason: string,
		immediate = false,
	): void {
		const capture = resolveMouseCapture({
			hasPoint: true,
			isDraggingWindow: this.isDraggingWindow,
			mousePassthrough: this.mousePassthrough,
			hoverHysteresisPx: HOVER_HYSTERESIS_PX,
			hoveringInteractionArea: hovering,
		});

		const interaction = resolveInteractionMode({
			locked: this.config.locked,
			isDraggingWindow: this.isDraggingWindow,
			hoveringInteractionArea: hovering,
			interactMode: this.interactMode,
		});

		this.modelHovering = hovering;
		this.requestMousePassthrough(
			interaction.shouldIgnoreMouse,
			reason,
			immediate || capture.forceCapture,
		);
		this.updateCursor(interaction.cursor !== "default");
	}

	private syncMouseCaptureFromLastPoint(
		reason: string,
		immediate = false,
	): void {
		if (!this.lastMouseClientPoint) {
			if (!this.isDraggingWindow) {
				this.requestMousePassthrough(true, reason, immediate);
			}
			this.updateCursor(false);
			return;
		}

		this.syncMouseCaptureFromPoint(
			this.lastMouseClientPoint.x,
			this.lastMouseClientPoint.y,
			reason,
		);
	}

	private updateCursor(hoveringModel: boolean): void {
		if (!this.canvas) {
			return;
		}

		this.canvas.style.cursor = resolveCursor({
			hasCanvas: Boolean(this.canvas),
			isDraggingWindow: this.isDraggingWindow,
			hoveringModel,
			modelHovering: this.modelHovering,
			interactMode: this.interactMode,
			locked: this.config.locked,
		});
	}

	private startPerformanceController(): void {
		this.performanceController?.start();
	}

	private stopPerformanceController(): void {
		this.performanceController?.stop();
	}

	private syncVisibilityPerformance(): void {
		this.performanceController?.syncVisibility();
		this.applyRuntimePerformancePolicy();
	}

	private markActivity(reason: string): void {
		this.performanceController?.markActivity(reason);
	}

	private applyFpsTier(tier: PetFpsTier, reason: string): void {
		if (!this.app) {
			return;
		}

		this.currentFpsTier = tier;
		const targetFps = tier === "active" ? ACTIVE_FPS : IDLE_FPS;
		this.app.ticker.maxFPS = targetFps;
		this.app.ticker.minFPS = Math.min(targetFps, IDLE_FPS);
		this.applyRuntimePerformancePolicy();
		if (tier === "idle") {
			this.setBehaviorState("sleepy", 5200);
			this.emitPetEvent("onPetIdle", { reason });
		}
		logPetRendererDebug("[PetRenderer][perf] fps-tier switched", {
			tier,
			fps: targetFps,
			reason,
		});
	}

	private applyRuntimePerformancePolicy(): void {
		this.vrmRuntime?.setRenderPolicy({
			targetFps: this.currentFpsTier === "active" ? ACTIVE_FPS : IDLE_FPS,
			paused: document.hidden,
		});
	}

	private reportRendererMetrics(reason: string): void {
		if (!this.app) {
			return;
		}

		logPetRendererDebug("[PetRenderer][perf] metrics", {
			reason,
			dprCap: this.renderBudget.dprCap,
			antialias: this.renderBudget.antialias,
			powerPreference: this.renderBudget.powerPreference,
			resolution: this.app.renderer.resolution,
			renderWidth: this.app.renderer.width,
			renderHeight: this.app.renderer.height,
		});
	}

	private setupIPCListeners(): void {
		window.live2dApi?.on("pet:interact-toggle", (enabled: unknown) => {
			this.interactMode = Boolean(enabled);

			if (!this.interactMode && this.isDraggingWindow) {
				this.finishWindowDrag();
			}

			document.body.classList.toggle("interact-mode", this.interactMode);
			this.syncMouseCaptureFromLastPoint("interact-toggle", true);
		});

		window.live2dApi?.on("pet:apply-config", (data: unknown) => {
			this.applyConfig((data as PetControlConfigPatch) ?? {});
		});

		window.live2dApi?.on("pet:request-state", () => {
			this.reportState(true);
		});

		window.live2dApi?.on("pet:request-avatar-capabilities", () => {
			this.publishAvatarCapabilities();
		});

		window.live2dApi?.on("pet:avatar-command", (data: unknown) => {
			this.executeAvatarCommand(data);
		});

		window.live2dApi?.on("pet:trigger-expression", (data: unknown) => {
			const payload = data as { name?: string };
			if (payload?.name) {
				this.setExpression(payload.name);
			}
		});

		window.live2dApi?.on("pet:trigger-expression-mix", (data: unknown) => {
			const payload = data as PetExpressionMixPayload | undefined;
			if (
				payload?.expressions?.length ||
				payload?.parameterOverrides?.length ||
				payload?.motion
			) {
				this.setExpressionMix(payload);
			}
		});

		window.live2dApi?.on("pet:behavior-state", (data: unknown) => {
			const payload = data as
				| { state?: Live2DBehaviorState; durationMs?: number }
				| undefined;
			if (isLive2DBehaviorState(payload?.state)) {
				this.setBehaviorState(payload.state, payload.durationMs ?? 0);
			}
		});

		window.live2dApi?.on("pet:companion-idle-profile", (data: unknown) => {
			this.setCompanionIdleProfile(
				(data as PetCompanionIdleProfile | undefined) ?? {},
			);
		});

		window.live2dApi?.on("pet:lipsync-start", (data: unknown) => {
			const payload = data as { audioUrl?: string; requestId?: string } | undefined;
			if (payload?.audioUrl) {
				void this.startLipSync(payload.audioUrl, payload.requestId);
			}
		});

		window.live2dApi?.on("pet:lipsync-stop", (data: unknown) => {
			const payload = data as { interrupted?: boolean } | undefined;
			this.stopLipSync({ interrupted: payload?.interrupted === true });
		});

		window.live2dApi?.on("pet:lipsync-level", (data: unknown) => {
			const payload = data as PetLipSyncLevelPayload | undefined;
			if (payload?.source === "realtime" || payload?.source === "tts-pcm") {
				this.setExternalLipSync(payload);
			}
		});

		window.live2dApi?.on("pet:lipsync-viseme", (data: unknown) => {
			const payload = data as PetLipSyncVisemePayload | undefined;
			if (payload?.source === "tts-pcm") {
				this.setExternalViseme(payload);
			}
		});

		window.live2dApi?.on("pet:trigger-emotion", (data: unknown) => {
			const payload = data as PetResolvedEmotionTrigger | undefined;
			if (payload?.id) {
				this.triggerEmotion(payload);
			}
		});

		window.live2dApi?.on("pet:trigger-animation", (data: unknown) => {
			const payload = data as { name?: string; group?: string; index?: number };
			const motionGroup = payload?.group ?? payload?.name;
			if (motionGroup) {
				this.playMotion(motionGroup, payload?.index ?? 0);
			}
		});
	}

	private triggerModelClick(): void {
		if (this.isDraggingWindow || this.dragMoved) {
			return;
		}

		const now = Date.now();
		if (now - this.lastClickAt <= DOUBLE_CLICK_INTERVAL_MS) {
			if (this.singleClickTimer !== null) {
				window.clearTimeout(this.singleClickTimer);
				this.singleClickTimer = null;
			}
			this.lastClickAt = 0;
			this.focusedInteraction = !this.focusedInteraction;
			this.setBehaviorState(this.focusedInteraction ? "focused" : "waiting", 3200);
			this.testState.lastClickTriggeredAt = Date.now();
			this.syncTestState();
			this.emitPetEvent("onPetClicked", {
				gesture: "double_click",
				mode: this.focusedInteraction ? "focused" : "companion",
			});
			this.markActivity("model-dblclick-toggle-focus");
			return;
		}

		this.lastClickAt = now;
		if (this.singleClickTimer !== null) {
			window.clearTimeout(this.singleClickTimer);
			this.singleClickTimer = null;
		}

		this.singleClickTimer = window.setTimeout(() => {
			this.singleClickTimer = null;
			this.setBehaviorState("curious", 1700);
			this.playRandomMotion();
			this.testState.lastClickTriggeredAt = Date.now();
			this.syncTestState();
			this.emitPetEvent("onPetClicked", { gesture: "single_click" });
			this.markActivity("model-click");
		}, DOUBLE_CLICK_INTERVAL_MS + 24);
	}

	private schedulePersistScale(): void {
		if (this.scalePersistTimer !== null) {
			window.clearTimeout(this.scalePersistTimer);
			this.scalePersistTimer = null;
		}

		this.scalePersistTimer = window.setTimeout(() => {
			this.scalePersistTimer = null;
			window.live2dApi?.pet.saveScale?.(this.config.scale);
		}, 180);
	}

	private schedulePersistPosition(): void {
		if (this.positionPersistTimer !== null) {
			window.clearTimeout(this.positionPersistTimer);
			this.positionPersistTimer = null;
		}
		if (
			typeof this.config.positionX !== "number" ||
			typeof this.config.positionY !== "number"
		) {
			return;
		}

		this.positionPersistTimer = window.setTimeout(() => {
			this.positionPersistTimer = null;
			if (
				typeof this.config.positionX === "number" &&
				typeof this.config.positionY === "number"
			) {
				window.live2dApi?.pet.savePosition?.(
					this.config.positionX,
					this.config.positionY,
				);
			}
		}, 180);
	}

	private readonly handleWindowMouseDown = (event: MouseEvent): void => {
		this.hideQuickMenu();

		if (this.config.clickThrough) {
			return;
		}

		const down = resolveMouseDown({
			button: event.button,
			clientX: event.clientX,
			clientY: event.clientY,
		});

		if (down.shouldIgnore) {
			return;
		}

		this.lastMouseClientPoint = down.nextMousePoint;
		this.dragMoved = down.nextDragMoved;
		this.mouseDownOnModel = down.nextMouseDownOnModel;
	};

	private readonly handleWindowMouseMove = (event: MouseEvent): void => {
		if (this.config.clickThrough) {
			return;
		}

		this.lastMouseClientPoint = { x: event.clientX, y: event.clientY };
		this.cancelLongPressWhenMoved(this.lastMouseClientPoint);

		if (this.isDraggingWindow && this.dragLastScreen && !this.config.locked) {
			this.setAttentionFromClientPoint(this.lastMouseClientPoint, 0.24, 520);
			const dragDelta = resolveMouseMove(
				{
					isDraggingWindow: this.isDraggingWindow,
					dragLastScreen: this.dragLastScreen,
					dragLastClient: this.dragLastClient,
				},
				event,
			);

			if (dragDelta) {
				const wasMoved = this.dragMoved;
				const currentAnchor = resolveModelAnchor({
					viewportWidth: window.innerWidth,
					viewportHeight: window.innerHeight,
					positionX: this.config.positionX,
					positionY: this.config.positionY,
					placement: this.config.placement,
				});
				this.config.positionX = currentAnchor.x + dragDelta.deltaX;
				this.config.positionY = currentAnchor.y + dragDelta.deltaY;
				this.config.placement = "free";
				this.applyModelTransform();
				this.schedulePersistPosition();
				this.dragLastScreen = dragDelta.nextScreen;
				this.dragLastClient = dragDelta.nextClient;
				this.dragMoved =
					this.dragMoved ||
					Math.abs(dragDelta.deltaX) > 0 ||
					Math.abs(dragDelta.deltaY) > 0;
				this.testState.dragMoveCount += 1;
				this.syncTestState();
				if (!wasMoved) {
					this.setBehaviorState("focused", 1100);
					this.emitPetEvent("onPetDragged", {
						phase: "start",
						x: Math.round(this.config.positionX ?? 0),
						y: Math.round(this.config.positionY ?? 0),
					});
				}
			}

			this.markActivity("window-drag");
			return;
		}

		this.hoverMoveCoalescer.submit({ x: event.clientX, y: event.clientY });
	};

	private processHoverMouseMove(point: { x: number; y: number }): void {
		if (this.destroyed || this.config.clickThrough || this.isDraggingWindow) return;

		this.lastMouseClientPoint = point;
		this.syncMouseCaptureFromPoint(point.x, point.y, "mousemove");
		this.setAttentionFromClientPoint(
			point,
			this.modelHovering ? 0.56 : 0.38,
			820,
		);
		this.markActivity("pointer-attention");
	}

	private readonly handleWindowMouseUp = (event: MouseEvent): void => {
		const moved = this.dragMoved;
		const wasDraggingWindow = this.isDraggingWindow;
		const menuWasOpened = this.longPressMenuOpen;
		this.clearLongPressTimer();
		this.longPressMenuOpen = false;

		if (this.isDraggingWindow) {
			this.finishWindowDrag();
			if (
				typeof this.config.positionX === "number" &&
				typeof this.config.positionY === "number"
			) {
				window.live2dApi?.pet.savePosition?.(
					this.config.positionX,
					this.config.positionY,
				);
			}
		}
		if (wasDraggingWindow && moved) {
			this.setBehaviorState("reacting", 1100);
			this.emitPetEvent("onPetDragged", {
				phase: "end",
				x: Math.round(this.config.positionX ?? 0),
				y: Math.round(this.config.positionY ?? 0),
			});
		}

		const clickAllowed = resolveMouseUp({
			button: event.button,
			mouseDownOnModel: this.mouseDownOnModel,
			moved,
			isDraggingWindow: wasDraggingWindow,
		});

		this.testState.lastMouseUpAt = Date.now();
		this.testState.lastMouseUpTriggeredClick = clickAllowed;
		this.syncTestState();

		this.mouseDownOnModel = false;
		this.dragMoved = false;

		if (clickAllowed && !menuWasOpened) {
			this.setAttentionFromClientPoint(this.lastMouseClientPoint, 0.72, 1200);
			this.triggerModelClick();
		}

		this.syncMouseCaptureFromLastPoint("mouseup");
	};

	private readonly handleWindowMouseLeave = (): void => {
		this.hoverMoveCoalescer.cancel();
		this.lastMouseClientPoint = null;
		this.modelHovering = false;
		this.clearLongPressTimer();

		const shouldRelease = resolveMouseLeave({
			isDraggingWindow: this.isDraggingWindow,
		});

		if (!shouldRelease) {
			return;
		}

		this.requestMousePassthrough(true, "mouse-leave");
		this.updateCursor(false);
	};

	private readonly handleWindowContextMenu = (event: MouseEvent): void => {
		const point = this.getCanvasPointFromClient(event.clientX, event.clientY);
		const shouldHandle = resolveContextMenu({
			hasPoint: Boolean(point),
			insideInteractionArea: point
				? this.isPointInsideInteractionArea(point.x, point.y)
				: false,
		});

		if (!shouldHandle) {
			return;
		}

		event.preventDefault();
		this.setBehaviorState("waiting", 2200);
		this.showQuickMenu(event.clientX, event.clientY);
		this.emitPetEvent("onPetClicked", {
			gesture: "context_menu",
			x: Math.round(event.clientX),
			y: Math.round(event.clientY),
		});
		this.markActivity("model-right-click");
	};

	private readonly handleWindowWheel = (event: WheelEvent): void => {
		if (this.config.clickThrough || this.config.locked) {
			return;
		}

		const point = this.getCanvasPointFromClient(event.clientX, event.clientY);
		const wheel = resolveWheel({
			isDraggingWindow: this.isDraggingWindow,
			buttons: event.buttons,
			hasPoint: Boolean(point),
			insideInteractionArea: point
				? this.isPointInsideInteractionArea(
						point.x,
						point.y,
						HOVER_HYSTERESIS_PX,
					)
				: false,
			currentScale: this.config.scale,
			minScale: MIN_SCALE,
			maxScale: MAX_SCALE,
			deltaY: event.deltaY,
		});

		if (wheel.shouldPreventDefault) {
			event.preventDefault();
		}

		if (wheel.shouldIgnore) {
			return;
		}

		this.setScale(wheel.nextScale, false);
		this.reportState(true);
		this.schedulePersistScale();
		this.syncMouseCaptureFromPoint(event.clientX, event.clientY, "wheel");
		this.setAttentionFromClientPoint(
			{ x: event.clientX, y: event.clientY },
			0.54,
			900,
		);
		this.markActivity("wheel-scale");
	};

	private readonly handleResize = (): void => {
		if (!this.app) {
			return;
		}

		this.app.renderer.resize(window.innerWidth, window.innerHeight);
		this.vrmRuntime?.resize(window.innerWidth, window.innerHeight);
		this.applyModelTransform();
		this.reportRendererMetrics("resize");

		this.syncMouseCaptureFromLastPoint("resize", true);
	};

	private readonly handleWindowError = (event: ErrorEvent): void => {
		logger.error("[PetRenderer] window error:", event.message);
	};

	private readonly handleUnhandledRejection = (
		event: PromiseRejectionEvent,
	): void => {
		logger.error("[PetRenderer] unhandled rejection:", event.reason);
	};

	private readonly handleVisibilityChange = (): void => {
		this.syncVisibilityPerformance();
	};

	private finishWindowDrag(): void {
		const result = resolveDragEnd(this.isDraggingWindow, Date.now());
		if (!result.shouldFinish) {
			return;
		}

		this.isDraggingWindow = false;
		this.dragLastScreen = null;
		this.dragLastClient = null;
		this.dragCooldownUntil = result.nextDragCooldownUntil;
		window.live2dApi?.pet.endWindowDrag?.();
		this.markActivity("window-drag-end");
		this.dragMoved = result.nextDragMoved;
		this.modelHovering = result.nextModelHovering;
		this.testState.lastDragEndAt = result.draggedAt;
		this.syncTestState();
		this.syncMouseCaptureFromLastPoint("drag-end", true);
	}

	private syncTestState(): void {
		syncPetTestState(this.testState);
	}

	private emitPetEvent(event: DesktopPetEventName, payload: Record<string, unknown>): void {
		const detail: DesktopPetEventRecord = {
			event,
			payload,
			timestamp: new Date().toISOString(),
		};
		window.dispatchEvent(new CustomEvent("yuizaki:pet-event", { detail }));
		this.dispatchPetEventToPlugins(detail);
		logPetRendererDebug("[PetRenderer] pet event", detail);
	}

	private dispatchPetEventToPlugins(detail: DesktopPetEventRecord): void {
		const dispatcher = window.live2dApi?.pet?.dispatchEvent;
		if (!dispatcher) {
			return;
		}
		const now = Date.now();
		const intervalMs = PET_EVENT_DISPATCH_INTERVAL_MS[detail.event] ?? 0;
		const lastDispatchedAt = this.petEventDispatchAt.get(detail.event) ?? 0;
		if (now - lastDispatchedAt < intervalMs) {
			return;
		}
		this.petEventDispatchAt.set(detail.event, now);
		void dispatcher(detail).catch((error: unknown) => {
			logPetRendererDebug("[PetRenderer] pet event dispatch failed", error);
		});
	}

	private clearLongPressTimer(): void {
		if (this.longPressTimer !== null) {
			window.clearTimeout(this.longPressTimer);
			this.longPressTimer = null;
		}
		this.longPressOrigin = null;
	}

	private scheduleLongPressMenu(clientPoint: { x: number; y: number }): void {
		this.clearLongPressTimer();
		this.longPressMenuOpen = false;
		this.longPressOrigin = clientPoint;
		this.longPressTimer = window.setTimeout(() => {
			this.longPressTimer = null;
			if (this.dragMoved || !this.longPressOrigin) {
				return;
			}
			if (this.isDraggingWindow) {
				this.finishWindowDrag();
			}
			this.longPressMenuOpen = true;
			this.setBehaviorState("waiting", 2400);
			this.showQuickMenu(clientPoint.x, clientPoint.y);
			this.emitPetEvent("onPetClicked", {
				gesture: "long_press",
				x: Math.round(clientPoint.x),
				y: Math.round(clientPoint.y),
			});
			this.markActivity("model-long-press-menu");
		}, LONG_PRESS_MENU_MS);
	}

	private cancelLongPressWhenMoved(clientPoint: { x: number; y: number }): void {
		if (!this.longPressOrigin) {
			return;
		}
		const deltaX = clientPoint.x - this.longPressOrigin.x;
		const deltaY = clientPoint.y - this.longPressOrigin.y;
		if (Math.hypot(deltaX, deltaY) >= LONG_PRESS_MOVE_CANCEL_PX) {
			this.clearLongPressTimer();
		}
	}

	private showQuickMenu(clientX: number, clientY: number): void {
		const menu = this.ensureQuickMenu();
		menu.style.left = `${Math.min(Math.max(8, clientX), Math.max(8, window.innerWidth - 156))}px`;
		menu.style.top = `${Math.min(Math.max(8, clientY), Math.max(8, window.innerHeight - 170))}px`;
		menu.style.display = "block";
		this.requestMousePassthrough(false, "quick-menu", true);
	}

	private hideQuickMenu(): void {
		if (this.quickMenuEl) {
			this.quickMenuEl.style.display = "none";
		}
	}

	private ensureQuickMenu(): HTMLDivElement {
		if (this.quickMenuEl) {
			return this.quickMenuEl;
		}

		const menu = document.createElement("div");
		menu.className = "pet-quick-menu";

		const addButton = (label: string, action: () => void) => {
			const button = document.createElement("button");
			button.type = "button";
			button.textContent = label;
			button.addEventListener("click", (event) => {
				event.stopPropagation();
				action();
				this.hideQuickMenu();
			});
			menu.appendChild(button);
		};

		addButton("打开聊天", () => window.live2dApi?.pet.openChatCenter?.());
		addButton("锁定 / 解锁", () => {
			void window.live2dApi?.pet.setLocked?.(!this.config.locked);
		});
		addButton("回到右下角", () => {
			void window.live2dApi?.pet.snapBottomRight?.();
		});
		addButton("开启鼠标穿透", () => {
			void window.live2dApi?.pet.setClickThrough?.(true);
		});
		addButton("重新加载模型", () => {
			void window.live2dApi?.pet.reloadRenderer?.();
		});

		document.body.appendChild(menu);
		this.quickMenuEl = menu;
		return menu;
	}

	destroy(): void {
		this.destroyed = true;
		this.modelLoadGeneration += 1;
		this.cancelModelLoadRetry();
		this.embodiment.destroy();
		this.hoverMoveCoalescer.cancel();
		this.clearAvatarScheduling();

		if (this.singleClickTimer !== null) {
			window.clearTimeout(this.singleClickTimer);
			this.singleClickTimer = null;
		}
		this.clearLongPressTimer();

		if (this.passthroughTimer !== null) {
			window.clearTimeout(this.passthroughTimer);
			this.passthroughTimer = null;
		}

		if (this.scalePersistTimer !== null) {
			window.clearTimeout(this.scalePersistTimer);
			this.scalePersistTimer = null;
		}

		if (this.positionPersistTimer !== null) {
			window.clearTimeout(this.positionPersistTimer);
			this.positionPersistTimer = null;
		}

		this.quickMenuEl?.remove();
		this.quickMenuEl = null;

		this.stopPerformanceController();
		this.performanceController = null;
		document.removeEventListener('visibilitychange', this.handleVisibilityChange);
		detachWindowListeners({
			handleWindowMouseDown: this.handleWindowMouseDown,
			handleWindowMouseMove: this.handleWindowMouseMove,
			handleWindowMouseUp: this.handleWindowMouseUp,
			handleWindowMouseLeave: this.handleWindowMouseLeave,
			handleWindowWheel: this.handleWindowWheel,
			handleResize: this.handleResize,
			handleWindowContextMenu: this.handleWindowContextMenu,
			handleWindowError: this.handleWindowError,
			handleUnhandledRejection: this.handleUnhandledRejection,
		});

		if (this.model) {
			this.model = destroyCurrentModel(this.app, this.model);
		}

		if (this.live2dViewport) {
			this.app?.stage.removeChild(this.live2dViewport);
			this.live2dViewport.destroy();
			this.live2dViewport = null;
		}

		if (this.live2dRuntime) {
			this.live2dRuntime.destroy();
			this.live2dRuntime = null;
		}

		if (this.vrmRuntime) {
			this.vrmRuntime.destroy();
			this.vrmRuntime = null;
		}

		if (this.app) {
			this.app.destroy(true);
			this.app = null;
		}
	}

	private showNotice(text: string): void {
		if (!this.noticeEl) {
			this.noticeEl = document.createElement("div");
			this.noticeEl.className = "pet-notice";
			document.body.appendChild(this.noticeEl);
		}

		this.noticeEl.textContent = text;
		this.noticeEl.style.display = "block";
	}

	private hideNotice(): void {
		if (this.noticeEl) {
			this.noticeEl.style.display = "none";
		}
	}
}

export { PetRenderer };
