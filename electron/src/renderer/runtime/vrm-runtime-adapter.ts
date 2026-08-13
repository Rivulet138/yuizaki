import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm'
import {
  createAvatarCapabilityRevision,
  type AvatarAction,
  type AvatarActionExecutionResult,
  type AvatarBehavior,
  type AvatarCapabilitySnapshot,
} from '../../shared/avatar-command'
import {
  normalizePetLipSyncProfile,
  type PetCompanionIdleProfile,
  type PetControlConfigPatch,
  type PetLipSyncProfile,
  type PetLipSyncViseme,
  type PetRendererStatePayload,
} from '../../shared/pet-control'
import type { PetRuntimeAdapter, PetRuntimeRenderPolicy } from './pet-runtime-adapter'
import { resolvePetRenderBudget } from '../pet-render-budget'

interface VrmHostContext {
  container: HTMLElement
  config: {
    modelId: string | null
    modelType: 'live2d' | 'vrm'
    modelPath: string
    animationPaths: string[]
    scale: number
    positionX: number | null
    positionY: number | null
    placement: 'bottom-right' | 'free'
    lipSyncProfile: PetLipSyncProfile
  }
  showNotice(text: string): void
  hideNotice(): void
  reportState(force?: boolean): void
  markActivity(reason: string): void
}

export interface VrmBehaviorProfile {
  gazeAmplitude: number
  swayAmplitude: number
  breathAmplitude: number
  breathSpeed: number
  expressionWeight: number
  motionFadeMs: number
  motionLoop: boolean
}

const clampUnit = (value: unknown, fallback: number): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : fallback
}

const normalizeVrmBehaviorProfile = (behavior: AvatarBehavior): VrmBehaviorProfile => {
  switch (behavior) {
    case 'listen':
      return { gazeAmplitude: 0.05, swayAmplitude: 0.028, breathAmplitude: 0.045, breathSpeed: 0.85, expressionWeight: 0.34, motionFadeMs: 180, motionLoop: true }
    case 'think':
      return { gazeAmplitude: 0.12, swayAmplitude: 0.035, breathAmplitude: 0.04, breathSpeed: 0.72, expressionWeight: 0.28, motionFadeMs: 220, motionLoop: true }
    case 'speak':
      return { gazeAmplitude: 0.04, swayAmplitude: 0.022, breathAmplitude: 0.045, breathSpeed: 0.92, expressionWeight: 0.3, motionFadeMs: 140, motionLoop: true }
    case 'backchannel':
      return { gazeAmplitude: 0.1, swayAmplitude: 0.05, breathAmplitude: 0.055, breathSpeed: 1.08, expressionWeight: 0.48, motionFadeMs: 120, motionLoop: false }
    case 'react':
      return { gazeAmplitude: 0.16, swayAmplitude: 0.085, breathAmplitude: 0.065, breathSpeed: 1.25, expressionWeight: 0.7, motionFadeMs: 100, motionLoop: false }
    case 'idle':
    default:
      return { gazeAmplitude: 0.025, swayAmplitude: 0.018, breathAmplitude: 0.04, breathSpeed: 0.7, expressionWeight: 0.22, motionFadeMs: 240, motionLoop: true }
  }
}

export const resolveVrmBehaviorProfile = (
  behavior: AvatarBehavior,
  companion: PetCompanionIdleProfile = {},
): VrmBehaviorProfile => {
  const profile = normalizeVrmBehaviorProfile(behavior)
  const energy = clampUnit(companion.energy, 0.5)
  const warmth = (clampUnit(companion.affinity, 0.5) + clampUnit(companion.trust, 0.5) + clampUnit(companion.intimacy, 0.5)) / 3
  const trend = companion.relationshipTrend === 'rising' ? 0.08 : companion.relationshipTrend === 'flat' ? -0.04 : 0
  const curious = companion.mood === 'curious' || companion.supportStyle === 'analytical'
  const cheerful = companion.mood === 'warm' || companion.supportStyle === 'cheerful'
  const fatigue = clampUnit(companion.fatigue, 0)
  const activity = Math.max(0.45, Math.min(1.2, 0.72 + energy * 0.42 + trend - fatigue * 0.32))
  const gazeBias = curious ? 0.05 : cheerful ? 0.015 : 0
  const expressionBias = cheerful ? 0.08 : curious ? 0.03 : 0
  return {
    gazeAmplitude: Math.max(0, Math.min(0.3, profile.gazeAmplitude * activity + gazeBias)),
    swayAmplitude: Math.max(0, Math.min(0.18, profile.swayAmplitude * activity + (cheerful ? 0.012 : 0))),
    breathAmplitude: Math.max(0, Math.min(0.14, profile.breathAmplitude * activity)),
    breathSpeed: Math.max(0.2, Math.min(2, profile.breathSpeed * activity)),
    expressionWeight: Math.max(0, Math.min(1, profile.expressionWeight * (0.75 + warmth * 0.35) + expressionBias)),
    motionFadeMs: profile.motionFadeMs,
    motionLoop: profile.motionLoop,
  }
}

export class VrmRuntimeAdapter implements PetRuntimeAdapter {
  readonly modelType = 'vrm' as const

  private canvas: HTMLCanvasElement | null = null
  private renderer: THREE.WebGLRenderer | null = null
  private scene: THREE.Scene | null = null
  private camera: THREE.PerspectiveCamera | null = null
  private light: THREE.DirectionalLight | null = null
  private ambientLight: THREE.AmbientLight | null = null
  private timer = new THREE.Timer()
  private vrm: VRM | null = null
  private animationMixer: THREE.AnimationMixer | null = null
  private animationClips: THREE.AnimationClip[] = []
  private activeAnimationAction: THREE.AnimationAction | null = null
  private rafId: number | null = null
  private renderLoopGeneration = 0
  private targetFps = 60
  private renderPaused = false
  private lastRenderedAt = 0
  private lipSyncOpen = 0
  private activeLipSyncViseme: PetLipSyncViseme | null = null
  private activeLipSyncVisemeWeight = 1
  private appliedLipSyncExpression: Exclude<PetLipSyncViseme, 'sil'> | null = null
  private readonly expressionStates = new Map<string, {
    current: number
    target: number
    fadeMs: number
    expiresAt: number | null
    fadeOutMs: number
  }>()
  private gazeTarget: { x: number; y: number; strength: number; expiresAt: number | null } | null = null
  private smoothedGaze = new THREE.Vector2()
  private readonly lookAtOrigin = new THREE.Vector3()
  private readonly lookAtTarget = new THREE.Vector3()
  private behavior: AvatarBehavior = 'idle'
  private behaviorStartedAt = performance.now()
  private companionIdleProfile: PetCompanionIdleProfile = {}
  private behaviorProfile: VrmBehaviorProfile = resolveVrmBehaviorProfile('idle')
  private loadGeneration = 0
  private readonly renderBudget = resolvePetRenderBudget({
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory,
  })

  constructor(private readonly host: VrmHostContext) {}

  getCapabilities(): AvatarCapabilitySnapshot {
    const expressions = Object.keys(this.vrm?.expressionManager?.expressionMap ?? {})
    const gaze = Boolean(this.vrm?.lookAt)
    const motions = this.animationClips.map((clip, index) => ({
      group: clip.name || `clip-${index}`,
      index,
      ...(clip.name ? { label: clip.name } : {}),
    }))
    const revision = createAvatarCapabilityRevision('vrm', this.host.config.modelId, [
      ...expressions,
      gaze ? 'lookAt' : 'no-lookAt',
      ...motions.map((motion) => `${motion.group}:${motion.index}`),
    ])
    return {
      revision,
      modelType: 'vrm',
      modelId: this.host.config.modelId,
      generatedAt: Date.now(),
      actions: {
        behavior: true,
        affect: expressions.length > 0,
        gaze,
        motion: motions.length > 0,
        expression: expressions.length > 0,
        parameterPatch: false,
        viseme: expressions.some((name) => ['aa', 'ih', 'ou', 'ee', 'oh'].includes(name)),
        cancel: true,
      },
      expressions,
      motions,
      parameters: [],
    }
  }

  executeAvatarAction(action: AvatarAction): AvatarActionExecutionResult {
    switch (action.type) {
      case 'behavior':
        this.behavior = action.behavior
        this.behaviorStartedAt = performance.now()
        this.behaviorProfile = resolveVrmBehaviorProfile(this.behavior, this.companionIdleProfile)
        return { status: 'completed' }
      case 'affect': {
        const expression = this.resolveVrmExpression(action.emotion)
        if (!expression) return { status: 'degraded', message: `VRM expression not available: ${action.emotion}` }
        this.setExpressionTarget(expression, (action.intensity ?? 1) * this.behaviorProfile.expressionWeight, 160, action.decayMs ?? 1800)
        return { status: 'completed' }
      }
      case 'gaze':
        if (!this.vrm?.lookAt) return { status: 'degraded', message: 'VRM model has no LookAt capability' }
        this.gazeTarget = {
          x: action.target.x,
          y: action.target.y,
          strength: action.strength ?? 0.75,
          expiresAt: action.holdMs ? performance.now() + action.holdMs : null,
        }
        return { status: 'completed' }
      case 'motion':
        return this.playAnimation(action.group, action.index ?? 0, action.intensity ?? 1)
      case 'expression': {
        const expression = this.resolveVrmExpression(action.name)
        if (!expression) return { status: 'degraded', message: `VRM expression not available: ${action.name}` }
        this.setExpressionTarget(expression, (action.weight ?? 1) * this.behaviorProfile.expressionWeight, action.fadeInMs ?? 160, action.fadeOutMs ?? 1200)
        return { status: 'completed' }
      }
      case 'parameterPatch':
        return { status: 'degraded', message: 'Raw parameter patches are not defined for VRM' }
      case 'viseme':
        this.setLipSyncViseme(action.viseme, action.weight ?? 1, action.active ?? true)
        return { status: 'completed' }
      case 'cancel':
        if (action.channel === 'gaze') {
          this.gazeTarget = null
          return { status: 'completed' }
        }
        if (action.channel === 'viseme') {
          this.setLipSyncViseme('sil', 0, false)
          return { status: 'completed' }
        }
        if (action.channel === 'behavior') {
          this.behavior = 'idle'
          this.behaviorProfile = resolveVrmBehaviorProfile('idle', this.companionIdleProfile)
          return { status: 'completed' }
        }
        if (action.channel === 'motion') {
          this.stopAnimation()
          return { status: 'completed' }
        }
        if (action.channel === 'expression' || action.channel === 'affect') {
          this.expressionStates.forEach((state) => {
            state.target = 0
            state.expiresAt = null
          })
          return { status: 'completed' }
        }
        this.expressionStates.forEach((state) => {
          state.target = 0
          state.expiresAt = null
        })
        this.gazeTarget = null
        this.behavior = 'idle'
        this.behaviorProfile = resolveVrmBehaviorProfile('idle', this.companionIdleProfile)
        this.setLipSyncViseme('sil', 0, false)
        return { status: 'completed' }
    }
  }

  setCompanionIdleProfile(profile: PetCompanionIdleProfile): void {
    this.companionIdleProfile = { ...profile }
    this.behaviorProfile = resolveVrmBehaviorProfile(this.behavior, this.companionIdleProfile)
  }

  setAttentionTarget(target: { x: number; y: number; strength?: number; durationMs?: number } | null): void {
    if (!target) {
      this.gazeTarget = null
      return
    }
    const strength = clampUnit(target.strength, 0.75)
    this.gazeTarget = {
      x: Math.max(-1, Math.min(1, Number.isFinite(target.x) ? target.x : 0)),
      y: Math.max(-1, Math.min(1, Number.isFinite(target.y) ? target.y : 0)),
      strength,
      expiresAt: target.durationMs && target.durationMs > 0 ? performance.now() + Math.min(4_000, target.durationMs) : null,
    }
  }

  async loadModel(config: PetControlConfigPatch): Promise<void> {
    const generation = ++this.loadGeneration
    const modelPath = config.modelPath ?? this.host.config.modelPath
    this.host.config.modelPath = modelPath
    if (Array.isArray(config.animationPaths)) {
      this.host.config.animationPaths = [...config.animationPaths]
    }

    this.ensureRenderer()
    const loaded = await this.loadVrm(modelPath, generation, this.host.config.animationPaths)
    if (!loaded || generation !== this.loadGeneration) return
    this.behaviorProfile = resolveVrmBehaviorProfile(this.behavior, this.companionIdleProfile)
    this.applyConfig(config)
    this.startLoop()
    this.host.hideNotice()
    this.host.markActivity('vrm-loaded')
    this.host.reportState(true)
  }

  applyConfig(_config: PetControlConfigPatch): void {
    if (!this.vrm) {
      return
    }

    const normalizedScale = Math.max(0.2, Math.min(0.8, this.host.config.scale))
    this.vrm.scene.scale.setScalar(normalizedScale)
    this.vrm.scene.position.set(0, -1.35, 0)

    if (this.camera) {
      this.camera.position.set(0, 1.35, 3.1)
      this.camera.lookAt(0, 1.2, 0)
      this.camera.updateProjectionMatrix()
    }
  }

  setLipSyncLevel(level: number, active: boolean): void {
    const expressionManager = this.vrm?.expressionManager
    if (!expressionManager) return
    if (!active) {
      this.lipSyncOpen = 0
      this.clearAppliedLipSyncExpression()
      return
    }
    const profile = normalizePetLipSyncProfile(this.host.config.lipSyncProfile)
    const target = level < profile.noiseGate
      ? 0
      : Math.max(0, Math.min(profile.maxOpen, level * profile.gain))
    const current = this.lipSyncOpen
    const smoothing = target > current ? profile.attack : profile.release
    this.lipSyncOpen = current + (target - current) * smoothing
    this.applyLipSyncExpression()
  }

  setLipSyncViseme(viseme: PetLipSyncViseme, weight: number, active: boolean): void {
    this.activeLipSyncViseme = active ? viseme : null
    this.activeLipSyncVisemeWeight = active ? Math.max(0, Math.min(1, weight)) : 1
    this.applyLipSyncExpression()
  }

  getState(): PetRendererStatePayload {
    return {
      modelType: 'vrm',
      modelId: this.host.config.modelId,
      scale: this.host.config.scale,
      positionX: typeof this.host.config.positionX === 'number' ? this.host.config.positionX : 0,
      positionY: typeof this.host.config.positionY === 'number' ? this.host.config.positionY : 0,
      placement: this.host.config.placement,
      ready: Boolean(this.vrm),
    }
  }

  setRenderPolicy(policy: PetRuntimeRenderPolicy): void {
    this.targetFps = Math.max(1, Math.min(120, Math.round(policy.targetFps)))
    this.renderPaused = policy.paused
    if (this.renderPaused) {
      this.renderLoopGeneration += 1
      if (this.rafId !== null) window.cancelAnimationFrame(this.rafId)
      this.rafId = null
      this.lastRenderedAt = 0
      return
    }
    if (this.rafId === null && this.renderer && this.scene && this.camera) this.startLoop()
  }

  destroy(): void {
    this.loadGeneration += 1
    this.renderLoopGeneration += 1
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId)
      this.rafId = null
    }

    if (this.vrm) {
      this.setLipSyncLevel(0, false)
      this.disposeAnimationState()
      VRMUtils.deepDispose(this.vrm.scene)
      this.scene?.remove(this.vrm.scene)
      this.vrm = null
    }

    if (this.renderer) {
      this.renderer.dispose()
    }

    if (this.canvas?.parentElement) {
      this.canvas.parentElement.removeChild(this.canvas)
    }

    this.canvas = null
    this.renderer = null
    this.scene = null
    this.camera = null
    this.light = null
    this.ambientLight = null
    this.expressionStates.clear()
    this.gazeTarget = null
    this.smoothedGaze.set(0, 0)
  }

  resize(width: number, height: number): void {
    if (!this.renderer || !this.camera) {
      return
    }

    this.renderer.setSize(width, height, false)
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.renderBudget.dprCap))
    this.camera.aspect = width / Math.max(height, 1)
    this.camera.updateProjectionMatrix()
  }

  private ensureRenderer(): void {
    if (this.renderer && this.canvas && this.scene && this.camera) {
      this.resize(window.innerWidth, window.innerHeight)
      return
    }

    this.canvas = document.createElement('canvas')
    this.canvas.dataset.runtime = 'vrm'
    this.canvas.style.width = '100%'
    this.canvas.style.height = '100%'
    this.canvas.style.display = 'block'
    this.canvas.style.pointerEvents = 'none'
    this.host.container.appendChild(this.canvas)

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      alpha: true,
      antialias: this.renderBudget.antialias,
      preserveDrawingBuffer: false,
    })
    this.renderer.outputColorSpace = THREE.SRGBColorSpace

    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100)
    this.ambientLight = new THREE.AmbientLight(0xffffff, 1.15)
    this.light = new THREE.DirectionalLight(0xffffff, 1.35)
    this.light.position.set(1, 2, 3)

    this.scene.add(this.ambientLight)
    this.scene.add(this.light)
    this.resize(window.innerWidth, window.innerHeight)
  }

  private async loadVrm(modelPath: string, generation: number, animationPaths: string[]): Promise<boolean> {
    if (!this.scene || !this.renderer) {
      throw new Error('VRM renderer not initialized')
    }

    const scene = this.scene

    const loader = new GLTFLoader()
    loader.register((parser) => new VRMLoaderPlugin(parser))

    const gltf = await loader.loadAsync(modelPath)
    const vrm = gltf.userData.vrm as VRM | undefined
    if (!vrm) {
      throw new Error('Loaded glTF does not contain VRM data')
    }

    if (generation !== this.loadGeneration || this.scene !== scene) {
      VRMUtils.deepDispose(vrm.scene)
      return false
    }

    VRMUtils.rotateVRM0(vrm)
    const previousVrm = this.vrm
    this.disposeAnimationState()
    this.vrm = vrm
    const externalClips = await this.loadExternalAnimationClips(animationPaths, generation, scene)
    if (generation !== this.loadGeneration || this.scene !== scene) {
      VRMUtils.deepDispose(vrm.scene)
      return false
    }
    this.animationClips = [
      ...(Array.isArray(gltf.animations) ? gltf.animations : []),
      ...externalClips,
    ]
    this.animationMixer = this.animationClips.length > 0 ? new THREE.AnimationMixer(vrm.scene) : null
    scene.add(vrm.scene)
    if (previousVrm) {
      VRMUtils.deepDispose(previousVrm.scene)
      scene.remove(previousVrm.scene)
    }
    return true
  }

  private async loadExternalAnimationClips(
    animationPaths: string[],
    generation: number,
    scene: THREE.Scene,
  ): Promise<THREE.AnimationClip[]> {
    if (animationPaths.length === 0) return []
    const clips: THREE.AnimationClip[] = []
    for (const animationPath of animationPaths.slice(0, 32)) {
      if (generation !== this.loadGeneration || this.scene !== scene) return clips
      try {
        const loader = new GLTFLoader()
        const gltf = await loader.loadAsync(animationPath)
        if (generation !== this.loadGeneration || this.scene !== scene) return clips
        if (Array.isArray(gltf.animations)) clips.push(...gltf.animations)
      } catch (error) {
        console.warn(`[VrmRuntimeAdapter] failed to load VRMA animation: ${animationPath}`, error)
      }
    }
    return clips
  }

  private startLoop(): void {
    const generation = ++this.renderLoopGeneration
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId)
      this.rafId = null
    }

    this.timer.reset()
    this.lastRenderedAt = 0

    if (this.renderPaused) return

    const tick = (timestamp?: number) => {
      if (generation !== this.renderLoopGeneration || this.renderPaused) return
      this.rafId = window.requestAnimationFrame(tick)
      if (!this.renderer || !this.scene || !this.camera) {
        return
      }

      const frameAt = typeof timestamp === 'number' ? timestamp : performance.now()
      const minimumFrameInterval = 1000 / this.targetFps
      if (this.lastRenderedAt > 0 && frameAt - this.lastRenderedAt < minimumFrameInterval) return
      this.lastRenderedAt = frameAt

      this.timer.update(timestamp)
      const delta = this.timer.getDelta()
      this.updateExpressionBlend(delta)
      this.updateGaze(delta)
      this.animationMixer?.update(delta)
      this.vrm?.update(delta)
      this.renderer.render(this.scene, this.camera)
    }

    tick()
  }

  private applyLipSyncExpression(): void {
    const expressionManager = this.vrm?.expressionManager
    if (!expressionManager) return
    const requested = this.activeLipSyncViseme
    const nextExpression = requested && requested !== 'sil' && expressionManager.getExpression(requested)
      ? requested
      : requested === 'sil'
        ? null
        : expressionManager.getExpression('aa')
          ? 'aa'
          : null
    if (this.appliedLipSyncExpression && this.appliedLipSyncExpression !== nextExpression) {
      expressionManager.setValue(this.appliedLipSyncExpression, 0)
    }
    this.appliedLipSyncExpression = nextExpression
    if (nextExpression) {
      expressionManager.setValue(nextExpression, this.lipSyncOpen * this.activeLipSyncVisemeWeight)
    }
  }

  private playAnimation(group: string | undefined, index: number, intensity: number): AvatarActionExecutionResult {
    if (!this.animationMixer || this.animationClips.length === 0) {
      return { status: 'degraded', message: 'No VRM animation clip source is loaded' }
    }
    const normalizedGroup = group?.trim().toLowerCase()
    const clip = normalizedGroup
      ? this.animationClips.find((candidate, candidateIndex) => (
        candidate.name.toLowerCase() === normalizedGroup || `clip-${candidateIndex}` === normalizedGroup
      ))
      : this.animationClips[index]
    if (!clip) {
      return { status: 'degraded', message: `VRM animation clip not available: ${group || index}` }
    }
    this.activeAnimationAction?.fadeOut(this.behaviorProfile.motionFadeMs / 1000)
    const action = this.animationMixer.clipAction(clip)
    action.reset()
    action.setLoop(this.behaviorProfile.motionLoop ? THREE.LoopRepeat : THREE.LoopOnce, this.behaviorProfile.motionLoop ? Infinity : 1)
    action.clampWhenFinished = !this.behaviorProfile.motionLoop
    action.setEffectiveWeight(Math.max(0, Math.min(1, intensity)))
    action.fadeIn(this.behaviorProfile.motionFadeMs / 1000)
    action.play()
    this.activeAnimationAction = action
    this.host.markActivity(`vrm-motion:${clip.name || index}`)
    return { status: 'completed' }
  }

  private stopAnimation(): void {
    this.activeAnimationAction?.stop()
    this.activeAnimationAction = null
    this.animationMixer?.stopAllAction()
  }

  private disposeAnimationState(): void {
    this.stopAnimation()
    if (this.animationMixer && this.vrm) {
      this.animationMixer.uncacheRoot(this.vrm.scene)
    }
    this.animationMixer = null
    this.animationClips = []
  }

  private clearAppliedLipSyncExpression(): void {
    const expressionManager = this.vrm?.expressionManager
    if (expressionManager && this.appliedLipSyncExpression) {
      expressionManager.setValue(this.appliedLipSyncExpression, 0)
    }
    this.appliedLipSyncExpression = null
  }

  private resolveVrmExpression(name: string): string | null {
    const expressionManager = this.vrm?.expressionManager
    if (!expressionManager) return null
    const normalized = name.toLowerCase()
    const aliases: Record<string, string> = {
      joy: 'happy',
      happiness: 'happy',
      calm: 'relaxed',
      surprise: 'surprised',
      anger: 'angry',
    }
    const target = aliases[normalized] ?? normalized
    return Object.keys(expressionManager.expressionMap).find((key) => key.toLowerCase() === target) ?? null
  }

  private setExpressionTarget(name: string, target: number, fadeMs: number, fadeOutMs: number): void {
    const current = this.vrm?.expressionManager?.getValue(name) ?? 0
    this.expressionStates.set(name, {
      current,
      target: Math.max(0, Math.min(1, target)),
      fadeMs: Math.max(16, fadeMs),
      expiresAt: fadeOutMs > 0 ? performance.now() + fadeOutMs : null,
      fadeOutMs: Math.max(80, fadeOutMs),
    })
  }

  private updateExpressionBlend(deltaSeconds: number): void {
    const expressionManager = this.vrm?.expressionManager
    if (!expressionManager) return
    const now = performance.now()
    this.expressionStates.forEach((state, name) => {
      if (state.expiresAt !== null && now >= state.expiresAt) {
        state.target = 0
        state.fadeMs = state.fadeOutMs
        state.expiresAt = null
      }
      const alpha = 1 - Math.exp(-Math.max(0, deltaSeconds) * 1000 / Math.max(16, state.fadeMs))
      state.current += (state.target - state.current) * alpha
      expressionManager.setValue(name, Math.max(0, Math.min(1, state.current)))
      if (state.target === 0 && state.current < 0.002) {
        expressionManager.setValue(name, 0)
        this.expressionStates.delete(name)
      }
    })
  }

  private updateGaze(deltaSeconds: number): void {
    const lookAt = this.vrm?.lookAt
    if (!lookAt) return
    const now = performance.now()
    if (this.gazeTarget?.expiresAt !== null && this.gazeTarget?.expiresAt !== undefined && now >= this.gazeTarget.expiresAt) {
      this.gazeTarget = null
    }
    const elapsed = (now - this.behaviorStartedAt) / 1000
    const profile = this.behaviorProfile
    const idleX = Math.sin(elapsed * (0.38 + profile.breathSpeed * 0.18)) * profile.gazeAmplitude
    const idleY = Math.sin(elapsed * (0.27 + profile.breathSpeed * 0.12)) * profile.gazeAmplitude * 0.5
    const desiredX = this.gazeTarget?.x ?? idleX
    const desiredY = this.gazeTarget?.y ?? idleY
    const strength = this.gazeTarget?.strength ?? 1
    const alpha = 1 - Math.exp(-Math.max(0, deltaSeconds) * 8)
    this.smoothedGaze.x += (desiredX * strength - this.smoothedGaze.x) * alpha
    this.smoothedGaze.y += (desiredY * strength - this.smoothedGaze.y) * alpha
    lookAt.getLookAtWorldPosition(this.lookAtOrigin)
    this.lookAtTarget.copy(this.lookAtOrigin)
    this.lookAtTarget.x += this.smoothedGaze.x * 1.8
    this.lookAtTarget.y += this.smoothedGaze.y * 1.2
    this.lookAtTarget.z += 3
    lookAt.lookAt(this.lookAtTarget)
    const avatarScene = this.vrm?.scene
    if (!avatarScene) return
    if (this.behavior === 'idle' || this.behavior === 'listen' || this.behavior === 'think') {
      const breath = Math.sin(elapsed * Math.PI * 2 * profile.breathSpeed) * profile.breathAmplitude
      avatarScene.position.y = -1.35 + breath
      avatarScene.rotation.z = Math.sin(elapsed * 0.7) * profile.swayAmplitude
    } else {
      avatarScene.position.y = -1.35
      avatarScene.rotation.z = 0
    }
  }
}
