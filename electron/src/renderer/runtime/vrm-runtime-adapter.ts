import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm'
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

  constructor(private readonly host: VrmHostContext) {}

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
}
