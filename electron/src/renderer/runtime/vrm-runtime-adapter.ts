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
  type PetControlConfigPatch,
  type PetLipSyncProfile,
  type PetLipSyncViseme,
  type PetRendererStatePayload,
} from '../../shared/pet-control'
import type { PetRuntimeAdapter } from './pet-runtime-adapter'

interface VrmHostContext {
  container: HTMLElement
  config: {
    modelId: string | null
    modelType: 'live2d' | 'vrm'
    modelPath: string
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
  private rafId: number | null = null
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

  constructor(private readonly host: VrmHostContext) {}

  getCapabilities(): AvatarCapabilitySnapshot {
    const expressions = Object.keys(this.vrm?.expressionManager?.expressionMap ?? {})
    const gaze = Boolean(this.vrm?.lookAt)
    const revision = createAvatarCapabilityRevision('vrm', this.host.config.modelId, [
      ...expressions,
      gaze ? 'lookAt' : 'no-lookAt',
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
        motion: false,
        expression: expressions.length > 0,
        parameterPatch: false,
        viseme: expressions.some((name) => ['aa', 'ih', 'ou', 'ee', 'oh'].includes(name)),
        cancel: true,
      },
      expressions,
      motions: [],
      parameters: [],
    }
  }

  executeAvatarAction(action: AvatarAction): AvatarActionExecutionResult {
    switch (action.type) {
      case 'behavior':
        this.behavior = action.behavior
        this.behaviorStartedAt = performance.now()
        return { status: 'completed' }
      case 'affect': {
        const expression = this.resolveVrmExpression(action.emotion)
        if (!expression) return { status: 'degraded', message: `VRM expression not available: ${action.emotion}` }
        this.setExpressionTarget(expression, action.intensity ?? 1, 160, action.decayMs ?? 1800)
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
        return { status: 'degraded', message: 'No VRM animation clip source is loaded' }
      case 'expression': {
        const expression = this.resolveVrmExpression(action.name)
        if (!expression) return { status: 'degraded', message: `VRM expression not available: ${action.name}` }
        this.setExpressionTarget(expression, action.weight ?? 1, action.fadeInMs ?? 160, action.fadeOutMs ?? 1200)
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
        this.setLipSyncViseme('sil', 0, false)
        return { status: 'completed' }
    }
  }

  async loadModel(config: PetControlConfigPatch): Promise<void> {
    const modelPath = config.modelPath ?? this.host.config.modelPath
    this.host.config.modelPath = modelPath

    this.ensureRenderer()
    await this.loadVrm(modelPath)
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

  destroy(): void {
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId)
      this.rafId = null
    }

    if (this.vrm) {
      this.setLipSyncLevel(0, false)
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
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
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
      antialias: true,
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

  private async loadVrm(modelPath: string): Promise<void> {
    if (!this.scene || !this.renderer) {
      throw new Error('VRM renderer not initialized')
    }

    if (this.vrm) {
      VRMUtils.deepDispose(this.vrm.scene)
      this.scene.remove(this.vrm.scene)
      this.vrm = null
    }

    const loader = new GLTFLoader()
    loader.register((parser) => new VRMLoaderPlugin(parser))

    const gltf = await loader.loadAsync(modelPath)
    const vrm = gltf.userData.vrm as VRM | undefined
    if (!vrm) {
      throw new Error('Loaded glTF does not contain VRM data')
    }

    VRMUtils.rotateVRM0(vrm)
    this.scene.add(vrm.scene)
    this.vrm = vrm
  }

  private startLoop(): void {
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId)
      this.rafId = null
    }

    this.timer.reset()

    const tick = (timestamp?: number) => {
      this.rafId = window.requestAnimationFrame(tick)
      if (!this.renderer || !this.scene || !this.camera) {
        return
      }

      this.timer.update(timestamp)
      const delta = this.timer.getDelta()
      this.updateExpressionBlend(delta)
      this.updateGaze(delta)
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
    const idleAmplitude = this.behavior === 'think' ? 0.12 : this.behavior === 'listen' ? 0.05 : 0.025
    const desiredX = this.gazeTarget?.x ?? Math.sin(elapsed * 0.55) * idleAmplitude
    const desiredY = this.gazeTarget?.y ?? Math.sin(elapsed * 0.38) * idleAmplitude * 0.5
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
  }
}
