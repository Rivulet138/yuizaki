import { Config as Live2DConfig, type Live2DSprite, Priority } from 'easy-live2d'
import type * as PIXI from 'pixi.js'
import {
  createAvatarCapabilityRevision,
  type AvatarAction,
  type AvatarActionExecutionResult,
  type AvatarBehavior,
  type AvatarCapabilitySnapshot,
} from '../../shared/avatar-command'
import type {
  AvatarManifest,
  ExpressionLayer,
  PetCompanionIdleProfile,
  PetControlConfigPatch,
  PetExpressionMixPayload,
  PetParameterOverrideItem,
  PetRendererStatePayload,
  PetResolvedEmotionTrigger,
} from '../../shared/pet-control'
import { createLive2DModel, destroyCurrentModel } from '../pet-model-runtime'
import { ensureCubismCore } from '../pet-renderer-core'
import { Live2DBehaviorController } from './live2d-behavior-controller'
import type { Live2DAttentionTarget, Live2DBehaviorState } from './live2d-behavior-controller'
import type { Live2DCoreModel } from './live2d-core-model'
import { isObjectRecord, resolveLive2DCoreModel } from './live2d-core-model'
import { Live2DLipSyncController } from './live2d-lipsync-controller'
import type { PetRuntimeAdapter } from './pet-runtime-adapter'

interface ExpressionParameterList {
  getSize(): number
  at(index: number): unknown
}

interface ExpressionMotion {
  getExpressionParameters(): ExpressionParameterList
}

interface ExpressionStore {
  getValue(expression: string): unknown
}

interface ExpressionController {
  expressions?: ExpressionStore
}

type MotionCommand =
  | { kind: 'motion'; group: string; index: number; priority: number }
  | { kind: 'random'; group: string; priority: number }

const MOTION_TRANSITION_MIN_GAP_MS = 420
const MOTION_TRANSITION_DELAY_MS = 220

const hasExpressionStore = (value: unknown): value is ExpressionController => {
  if (!isObjectRecord(value)) {
    return false
  }
  const expressions = value.expressions
  return isObjectRecord(expressions) && typeof expressions.getValue === 'function'
}

const hasExpressionParameters = (value: unknown): value is ExpressionMotion =>
  isObjectRecord(value) && typeof value.getExpressionParameters === 'function'

const hasExpressionParameterList = (value: unknown): value is ExpressionParameterList =>
  isObjectRecord(value) && typeof value.getSize === 'function' && typeof value.at === 'function'

const resolveExpressionController = (model: unknown): ExpressionController | null => {
  if (!isObjectRecord(model)) {
    return null
  }
  const live2dModel = model._model
  if (!isObjectRecord(live2dModel)) {
    return null
  }
  return hasExpressionStore(live2dModel.expressionCtrl) ? live2dModel.expressionCtrl : null
}

interface Live2DHostContext {
  app: PIXI.Application | null
  getModel: () => Live2DSprite | null
  setModel: (model: Live2DSprite | null) => void
  getViewport: () => PIXI.Container | null
  ensureViewport: () => PIXI.Container
  config: {
    modelId: string | null
    modelType: 'live2d' | 'vrm'
    modelPath: string
    modelManifest: AvatarManifest | null
    lipSyncProfile: PetControlConfigPatch['lipSyncProfile']
    scale: number
    positionX: number | null
    positionY: number | null
    placement: 'bottom-right' | 'free'
  }
  showNotice(text: string): void
  hideNotice(): void
  installEasyLive2DInteractivity(): void
  setupModelInteractivity(): void
  applyModelTransform(): void
  reportState(force?: boolean): void
  syncMouseCaptureFromLastPoint(reason: string, immediate?: boolean): void
  markActivity(reason: string): void
}

export class Live2DRuntimeAdapter implements PetRuntimeAdapter {
  readonly modelType = 'live2d' as const
  private loadGeneration = 0
  private expressionMixTicker: ((ticker: PIXI.Ticker) => void) | null = null
  private activeMixState:
    | {
        startAt: number
        durationMs: number
        secondaryWeight: number
        coreModel: Live2DCoreModel
        secondaryParams: Array<{ id: string; blendType: number; value: number }>
        parameterOverrides: PetParameterOverrideItem[]
        baseSnapshot: Map<string, number>
      }
    | null = null
  private behaviorController: Live2DBehaviorController | null = null
  private lipSyncController: Live2DLipSyncController | null = null
  private companionIdleProfile: PetCompanionIdleProfile = {}
  private lastMotionStartedAt: number | null = null
  private pendingMotionTimer: ReturnType<typeof window.setTimeout> | null = null
  private pendingMotionCommand: MotionCommand | null = null

  constructor(private readonly host: Live2DHostContext) {}

  getCapabilities(): AvatarCapabilitySnapshot {
    const manifest = this.host.config.modelManifest
    const expressions = manifest?.expressions.map((expression) => expression.id) ?? []
    const motionIndexes = new Map<string, number>()
    const motions = manifest
      ? Object.entries(manifest.motions).map(([id, motion]) => {
          const group = motion.group ?? id
          const index = motionIndexes.get(group) ?? 0
          motionIndexes.set(group, index + 1)
          return { group, index, label: id }
        })
      : []
    const parameters = manifest?.parameterControls.map((parameter) => ({
      id: parameter.id,
      min: parameter.min,
      max: parameter.max,
      modes: ['set' as const],
    })) ?? []
    const revision = createAvatarCapabilityRevision('live2d', this.host.config.modelId, [
      ...expressions,
      ...motions.map((motion) => `${motion.group}:${motion.index}`),
      ...parameters.map((parameter) => parameter.id),
    ])

    return {
      revision,
      modelType: 'live2d',
      modelId: this.host.config.modelId,
      generatedAt: Date.now(),
      actions: {
        behavior: true,
        affect: expressions.length > 0,
        gaze: true,
        motion: motions.length > 0,
        expression: expressions.length > 0,
        parameterPatch: parameters.length > 0,
        viseme: Boolean(manifest?.lipSync?.parameterIds?.length),
        cancel: true,
      },
      expressions,
      motions,
      parameters,
    }
  }

  executeAvatarAction(action: AvatarAction): AvatarActionExecutionResult {
    switch (action.type) {
      case 'behavior':
        this.setBehaviorState(this.mapAvatarBehavior(action.behavior), action.durationMs ?? 0)
        return { status: 'completed' }
      case 'affect': {
        const expression = this.resolveExpressionName(action.emotion)
        if (!expression) return { status: 'degraded', message: `Expression not available: ${action.emotion}` }
        this.triggerExpressionMix({
          expressions: [{ expression, weight: action.intensity ?? 1 }],
          intensity: action.intensity ?? 1,
          durationMs: action.decayMs ?? 1800,
        })
        return { status: 'completed' }
      }
      case 'gaze':
        this.setAttentionTarget({
          x: action.target.x,
          y: action.target.y,
          strength: action.strength ?? 0.72,
          durationMs: action.holdMs ?? 1200,
        })
        return { status: 'completed' }
      case 'motion':
        if (!action.group) return { status: 'rejected', message: 'Live2D motion group is required' }
        this.triggerMotion(action.group, action.index ?? 0)
        return { status: 'completed' }
      case 'expression':
        if (!this.resolveExpressionName(action.name)) {
          return { status: 'degraded', message: `Expression not available: ${action.name}` }
        }
        this.triggerExpressionMix({
          expressions: [{ expression: action.name, weight: action.weight ?? 1 }],
          durationMs: action.fadeOutMs ?? 1800,
        })
        return { status: 'completed' }
      case 'parameterPatch': {
        const setPatches = action.patches.filter((patch) => (patch.mode ?? 'set') === 'set')
        if (setPatches.length === 0) {
          return { status: 'degraded', message: 'Live2D adapter currently supports set parameter patches only' }
        }
        this.applyParameterOverrides(setPatches.map((patch) => ({
          id: patch.id,
          value: patch.value,
          weight: patch.weight ?? 1,
        })))
        return setPatches.length === action.patches.length
          ? { status: 'completed' }
          : { status: 'degraded', message: 'Unsupported parameter blend modes were skipped' }
      }
      case 'viseme':
        if (!this.lipSyncController) return { status: 'degraded', message: 'Live2D lip-sync is not ready' }
        this.lipSyncController.setExternalViseme(action.weight ?? 1, action.active ?? true)
        return { status: 'completed' }
      case 'cancel':
        if (action.channel === 'gaze') {
          this.setAttentionTarget(null)
          return { status: 'completed' }
        }
        if (action.channel === 'motion') {
          this.clearPendingMotionTransition()
          return { status: 'completed' }
        }
        if (action.channel === 'viseme') {
          this.stopLipSync()
          return { status: 'completed' }
        }
        if (action.channel === 'behavior') {
          this.setBehaviorState('idle')
          return { status: 'completed' }
        }
        if (action.channel === 'expression' || action.channel === 'affect') {
          this.stopExpressionMixLoop()
          return { status: 'completed' }
        }
        this.setAttentionTarget(null)
        this.stopExpressionMixLoop()
        this.clearPendingMotionTransition()
        this.setBehaviorState('idle')
        return { status: 'completed' }
    }
  }

  private mapAvatarBehavior(behavior: AvatarBehavior): Live2DBehaviorState {
    const mapping: Record<AvatarBehavior, Live2DBehaviorState> = {
      idle: 'idle',
      listen: 'focused',
      think: 'thinking',
      speak: 'speaking',
      backchannel: 'curious',
      react: 'reacting',
    }
    return mapping[behavior]
  }

  private resolveExpressionName(name: string): string | null {
    const target = name.toLowerCase()
    const expression = this.host.config.modelManifest?.expressions.find((item) =>
      item.id.toLowerCase() === target
      || item.aliases?.some((alias) => alias.toLowerCase() === target),
    )
    return expression?.id ?? null
  }

  async loadModel(config: PetControlConfigPatch): Promise<void> {
    if (!this.host.app) {
      return
    }

    const generation = ++this.loadGeneration
    this.stopBehaviorControllers()

    const modelPath = config.modelPath ?? this.host.config.modelPath
    const currentModel = this.host.getModel()
    const viewport = this.host.ensureViewport()
    if (currentModel) {
      viewport.removeChild(currentModel)
    }
    this.host.setModel(destroyCurrentModel(this.host.app, currentModel))

    await ensureCubismCore()
    if (generation !== this.loadGeneration) return
    Live2DConfig.MotionGroupIdle = 'Idle'
    Live2DConfig.MouseFollow = false

    const model = createLive2DModel(modelPath)
    if (!model) {
      this.host.showNotice('Live2D model is empty.')
      return
    }
    if (generation !== this.loadGeneration) {
      destroyCurrentModel(this.host.app, model)
      return
    }

    model.anchor.set(0.5, 1)
    model.label = this.host.config.modelId ?? model.label
    this.host.config.modelPath = modelPath

    if ('setSize' in model && typeof model.setSize === 'function') {
      model.setSize({ height: window.innerHeight * 0.78, width: window.innerWidth * 0.32 })
    }

    if ('eventMode' in model) {
      ;(model as PIXI.Container & { eventMode?: string }).eventMode = 'none'
    }

    if ('interactiveChildren' in model) {
      ;(model as PIXI.Container & { interactiveChildren?: boolean }).interactiveChildren = false
    }

    this.host.setModel(model)
    this.host.installEasyLive2DInteractivity()
    this.host.setupModelInteractivity()
    viewport.addChild(model)
    this.host.applyModelTransform()
    this.host.hideNotice()
    this.host.markActivity('model-loaded')
    this.host.reportState(true)
    this.host.syncMouseCaptureFromLastPoint('model-loaded', true)
    this.startBehaviorControllers()
  }

  applyConfig(config: PetControlConfigPatch): void {
    this.lipSyncController?.configure(
      config.lipSyncProfile ?? this.host.config.lipSyncProfile,
      this.host.config.modelManifest?.lipSync?.parameterIds,
    )
  }

  triggerExpression(name: string, options?: { updateBehavior?: boolean }): void {
    const model = this.host.getModel()
    if (!model) {
      return
    }
    model.setExpression({ expressionId: name })
    if (options?.updateBehavior !== false) {
      this.setBehaviorState('reacting', 1400)
    }
  }

  triggerExpressionMix(payload: PetExpressionMixPayload): void {
    const model = this.host.getModel()
    if (!model) {
      return
    }

    const items = Array.isArray(payload.expressions)
      ? [...payload.expressions]
          .filter((item) => item?.expression)
          .sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1))
          .slice(0, 2)
      : []

    const parameterOverrides = Array.isArray(payload.parameterOverrides)
      ? payload.parameterOverrides.filter((item) => item?.id && typeof item.value === 'number').slice(0, 8)
      : []

    if (items.length === 0 && parameterOverrides.length === 0) {
      return
    }

    const intensity = Math.max(0, Math.min(1, payload.intensity ?? 1))
    const durationMs = Math.max(100, Math.min(10000, payload.durationMs ?? 1800))
    const primary = items[0]?.expression
    const secondary = items[1]?.expression

    if (primary) {
      model.setExpression({ expressionId: primary })
    }

    const coreModel = resolveLive2DCoreModel(model)
    if (!coreModel) {
      return
    }

    const expressionCtrl = resolveExpressionController(model)
    let secondaryParams: Array<{ id: string; blendType: number; value: number }> = []
    if (secondary && expressionCtrl?.expressions) {
      const secondaryMotion = expressionCtrl.expressions.getValue(secondary)
      if (hasExpressionParameters(secondaryMotion)) {
        secondaryParams = this.collectExpressionParams(secondaryMotion)
      }
    }

    const secondaryWeight = Math.max(0, Math.min(1, (items[1]?.weight ?? 0.5) * intensity))
    const baseSnapshot = new Map<string, number>()

    for (const item of [...secondaryParams, ...parameterOverrides.map((item) => ({ id: item.id }))]) {
      if (baseSnapshot.has(item.id)) continue
      try {
        baseSnapshot.set(item.id, Number(coreModel.getParameterValueById(item.id)))
      } catch {
        // ignore missing parameter ids
      }
    }

    const startAt = performance.now()

    this.stopExpressionMixLoop()
    this.activeMixState = {
      startAt,
      durationMs,
      secondaryWeight,
      coreModel,
      secondaryParams,
      parameterOverrides,
      baseSnapshot,
    }
    this.startExpressionMixLoop()
    this.setBehaviorState('reacting', durationMs)
  }

  applyExpressionMix(layers: ExpressionLayer[]): void {
    this.triggerExpressionMix({
      expressions: layers.map((layer) => ({ expression: layer.key, weight: layer.weight })),
    })
  }

  applyParameterOverrides(overrides: PetParameterOverrideItem[]): void {
    this.triggerExpressionMix({
      expressions: [],
      parameterOverrides: overrides,
    })
  }

  getCurrentModelManifest(): AvatarManifest | null {
    return this.host.config.modelManifest
  }

  private collectExpressionParams(motion: ExpressionMotion): Array<{ id: string; blendType: number; value: number }> {
    const params = motion.getExpressionParameters()
    if (!hasExpressionParameterList(params)) {
      return []
    }
    const result: Array<{ id: string; blendType: number; value: number }> = []
    const size = params.getSize()
    for (let i = 0; i < size; i += 1) {
      const item = params.at(i)
      if (!isObjectRecord(item) || !item.parameterId) continue
      result.push({
        id: String(item.parameterId),
        blendType: Number(item.blendType ?? 0),
        value: Number(item.value ?? 0),
      })
    }
    return result
  }

  private startExpressionMixLoop(): void {
    if (!this.host.app || !this.activeMixState || this.expressionMixTicker) {
      return
    }

    this.expressionMixTicker = () => {
      const mixState = this.activeMixState
      if (!mixState) {
        this.stopExpressionMixLoop()
        return
      }

      const elapsed = performance.now() - mixState.startAt
      const progress = Math.min(1, elapsed / mixState.durationMs)
      const fade = 1 - progress

      const applyParam = (parameterId: string, blendType: number, value: number, weight: number) => {
        const baseValue = mixState.baseSnapshot.get(parameterId)
        if (baseValue == null) return
        try {
          if (blendType === 0) {
            mixState.coreModel.setParameterValueById(parameterId, baseValue + value * weight, 1)
          } else if (blendType === 1) {
            mixState.coreModel.setParameterValueById(parameterId, baseValue * (1 + (value - 1) * weight), 1)
          } else {
            mixState.coreModel.setParameterValueById(parameterId, baseValue * (1 - weight) + value * weight, 1)
          }
        } catch {
          // ignore missing params
        }
      }

      for (const item of mixState.secondaryParams) {
        applyParam(item.id, item.blendType, item.value, mixState.secondaryWeight * fade)
      }

      for (const item of mixState.parameterOverrides) {
        const baseValue = mixState.baseSnapshot.get(item.id)
        if (baseValue == null) continue
        try {
          mixState.coreModel.setParameterValueById(
            item.id,
            baseValue * (1 - (item.weight ?? 1) * fade) + item.value * ((item.weight ?? 1) * fade),
            1,
          )
        } catch {
          // ignore missing params
        }
      }

      if (progress >= 1) {
        this.activeMixState = null
        this.stopExpressionMixLoop()
      }
    }

    this.host.app.ticker.add(this.expressionMixTicker)
  }

  private stopExpressionMixLoop(): void {
    if (this.host.app && this.expressionMixTicker) {
      this.host.app.ticker.remove(this.expressionMixTicker)
    }
    this.expressionMixTicker = null
  }

  triggerMotion(group: string, index = 0, options?: { updateBehavior?: boolean }): void {
    const model = this.host.getModel()
    if (!model) {
      return
    }
    this.playMotionWithTransition({
      kind: 'motion',
      group,
      index,
      priority: Priority.Normal,
    })
    if (options?.updateBehavior !== false) {
      this.setBehaviorState('reacting', 1800 + MOTION_TRANSITION_DELAY_MS)
    }
  }

  triggerRandomMotion(options?: { updateBehavior?: boolean }): void {
    const model = this.host.getModel()
    if (!model) {
      return
    }
    const groups = ['Idle', 'Tap', 'Tap@Body', 'Flick', 'Flick@Body']
    const group = groups[Math.floor(Math.random() * groups.length)]
    this.playMotionWithTransition({
      kind: 'random',
      group,
      priority: Priority.Normal,
    })
    if (options?.updateBehavior !== false) {
      this.setBehaviorState('reacting', 1500 + MOTION_TRANSITION_DELAY_MS)
    }
  }

  private playMotionWithTransition(command: MotionCommand): void {
    const now = performance.now()
    const elapsedSinceMotion = this.lastMotionStartedAt === null
      ? Number.POSITIVE_INFINITY
      : now - this.lastMotionStartedAt
    if (elapsedSinceMotion >= MOTION_TRANSITION_MIN_GAP_MS) {
      this.startMotionCommand(command)
      return
    }

    this.pendingMotionCommand = command
    if (this.pendingMotionTimer !== null) {
      window.clearTimeout(this.pendingMotionTimer)
    }
    const delayMs = Math.max(MOTION_TRANSITION_DELAY_MS, MOTION_TRANSITION_MIN_GAP_MS - elapsedSinceMotion)
    this.pendingMotionTimer = window.setTimeout(() => {
      this.pendingMotionTimer = null
      const pending = this.pendingMotionCommand
      this.pendingMotionCommand = null
      if (pending) {
        this.startMotionCommand(pending)
      }
    }, delayMs)
  }

  private startMotionCommand(command: MotionCommand): void {
    const model = this.host.getModel()
    if (!model) {
      return
    }

    this.lastMotionStartedAt = performance.now()
    if (command.kind === 'motion') {
      void model.startMotion({
        group: command.group,
        no: command.index,
        priority: command.priority,
      })
      return
    }

    void model.startRandomMotion({
      group: command.group,
      priority: command.priority,
    })
  }

  setBehaviorState(state: Live2DBehaviorState, durationMs = 0): void {
    this.behaviorController?.setState(state, durationMs)
  }

  setCompanionIdleProfile(profile: PetCompanionIdleProfile): void {
    this.companionIdleProfile = { ...profile }
    this.behaviorController?.setCompanionIdleProfile(profile)
  }

  setAttentionTarget(target: Live2DAttentionTarget | null): void {
    this.behaviorController?.setAttentionTarget(target)
  }

  getBehaviorDebugSnapshot(): ReturnType<Live2DBehaviorController['getDebugSnapshot']> | null {
    return this.behaviorController?.getDebugSnapshot() ?? null
  }

  async startLipSync(audioUrl: string, onReady?: () => void): Promise<void> {
    if (!this.lipSyncController) {
      return
    }
    this.setBehaviorState('speaking')
    await this.lipSyncController.start(audioUrl, onReady)
  }

  setLipSyncLevel(level: number, active: boolean): void {
    if (!this.lipSyncController) return
    if (active) {
      this.setBehaviorState('speaking')
      this.lipSyncController.setExternalLevel(level)
      return
    }
    this.lipSyncController.stopExternal()
    this.setBehaviorState('idle')
  }

  setLipSyncViseme(_viseme: PetLipSyncViseme, weight: number, active: boolean): void {
    this.lipSyncController?.setExternalViseme(weight, active)
    if (active) this.setBehaviorState('speaking')
  }

  stopLipSync(): void {
    this.lipSyncController?.stop()
    this.setBehaviorState('idle')
  }

  triggerEmotion(trigger: PetResolvedEmotionTrigger): void {
    if (trigger.expressionName) {
      this.triggerExpression(trigger.expressionName, { updateBehavior: false })
    }

    if (trigger.motion) {
      this.triggerMotion(trigger.motion.group, trigger.motion.index, { updateBehavior: false })
      this.setBehaviorState('reacting', 2200)
      return
    }

    if (!trigger.expressionName) {
      this.triggerRandomMotion({ updateBehavior: false })
    }

    this.setBehaviorState('reacting', 1600)
  }

  getState(): PetRendererStatePayload {
    return {
      modelType: 'live2d',
      modelId: this.host.config.modelId,
      scale: this.host.config.scale,
      positionX: typeof this.host.config.positionX === 'number' ? this.host.config.positionX : 0,
      positionY: typeof this.host.config.positionY === 'number' ? this.host.config.positionY : 0,
      placement: this.host.config.placement,
      ready: Boolean(this.host.getModel()),
    }
  }

  destroy(): void {
    this.stopBehaviorControllers()
    this.activeMixState = null
    this.stopExpressionMixLoop()
    this.clearPendingMotionTransition()
    if (!this.host.app) {
      return
    }
    const viewport = this.host.getViewport()
    const currentModel = this.host.getModel()
    if (viewport && currentModel) {
      viewport.removeChild(currentModel)
    }
    this.host.setModel(destroyCurrentModel(this.host.app, currentModel))
  }

  private startBehaviorControllers(): void {
    if (!this.host.app) {
      return
    }
    this.behaviorController = new Live2DBehaviorController(this.host.app, () => resolveLive2DCoreModel(this.host.getModel()))
    this.behaviorController.setCompanionIdleProfile(this.companionIdleProfile)
    this.behaviorController.start()
    this.lipSyncController = new Live2DLipSyncController(
      this.host.app,
      () => resolveLive2DCoreModel(this.host.getModel()),
      () => this.setBehaviorState('idle'),
    )
    this.lipSyncController.configure(
      this.host.config.lipSyncProfile,
      this.host.config.modelManifest?.lipSync?.parameterIds,
    )
  }

  private stopBehaviorControllers(): void {
    this.clearPendingMotionTransition()
    this.lipSyncController?.stop()
    this.lipSyncController = null
    this.behaviorController?.stop()
    this.behaviorController = null
  }

  private clearPendingMotionTransition(): void {
    if (this.pendingMotionTimer !== null) {
      window.clearTimeout(this.pendingMotionTimer)
    }
    this.pendingMotionTimer = null
    this.pendingMotionCommand = null
  }
}
