import { app } from 'electron'
import fs from 'fs'
import path from 'path'
import {
  DEFAULT_PET_CONTROL_STATE,
  PET_SCALE_DEFAULT,
  PET_SCALE_MIN,
  PET_SCALE_MAX,
  normalizePetLipSyncProfile,
  type PetControlConfigPatch,
  type PetLipSyncProfile,
  type PetControlState,
  type PetRendererStatePayload,
} from '../shared/pet-control'
import { logger } from './logger'

type PersistedPetState = Pick<
  PetControlState,
  | 'modelType'
  | 'modelId'
  | 'displayId'
  | 'scale'
  | 'positionX'
  | 'positionY'
  | 'placement'
  | 'visible'
  | 'doNotDisturb'
  | 'clickThrough'
  | 'locked'
  | 'opacity'
> & {
  lipSyncProfiles?: Record<string, Partial<PetLipSyncProfile>>
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value))
const MIN_PET_SCALE = PET_SCALE_MIN
const MAX_PET_SCALE = PET_SCALE_MAX
const LEGACY_DEFAULT_PET_SCALE = 0.28

const isPlacement = (value: unknown): value is PetControlState['placement'] =>
  value === 'bottom-right' ||
  value === 'bottom-left' ||
  value === 'top-right' ||
  value === 'top-left' ||
  value === 'center' ||
  value === 'free'

export class PetStateStore {
  private readonly filePath: string
  private state: PetControlState = {
    ...DEFAULT_PET_CONTROL_STATE,
    lipSyncProfile: { ...DEFAULT_PET_CONTROL_STATE.lipSyncProfile },
  }
  private lipSyncProfiles: Record<string, PetLipSyncProfile> = {}

  constructor() {
    this.filePath = path.join(app.getPath('userData'), 'pet-state.json')
    this.load()
  }

  getState(): PetControlState {
    return {
      ...this.state,
      lipSyncProfile: { ...this.state.lipSyncProfile },
    }
  }

  applyConfigPatch(patch: PetControlConfigPatch): PetControlState {
    const nextState: PetControlState = { ...this.state }
    const previousProfileKey = this.profileKey(nextState.modelId, nextState.modelType)

    if (patch.modelType === 'live2d' || patch.modelType === 'vrm') {
      nextState.modelType = patch.modelType
    }

    if (typeof patch.modelId === 'string' || patch.modelId === null) {
      nextState.modelId = patch.modelId
    }

    if (typeof patch.displayId === 'number' && Number.isFinite(patch.displayId)) {
      nextState.displayId = Math.trunc(patch.displayId)
    } else if (patch.displayId === null) {
      nextState.displayId = null
    }

    if (typeof patch.scale === 'number' && Number.isFinite(patch.scale)) {
      nextState.scale = clamp(patch.scale, MIN_PET_SCALE, MAX_PET_SCALE)
    }

    if (isPlacement(patch.placement)) {
      nextState.placement = patch.placement
      if (patch.placement !== 'free') {
        nextState.positionX = null
        nextState.positionY = null
      }
    }

    if (typeof patch.positionX === 'number' && typeof patch.positionY === 'number') {
      nextState.positionX = patch.positionX
      nextState.positionY = patch.positionY
      nextState.placement = 'free'
    }

    if (typeof patch.visible === 'boolean') {
      nextState.visible = patch.visible
    }

    if (typeof patch.doNotDisturb === 'boolean') {
      nextState.doNotDisturb = patch.doNotDisturb
    }

    if (typeof patch.clickThrough === 'boolean') {
      nextState.clickThrough = patch.clickThrough
    }

    if (typeof patch.locked === 'boolean') {
      nextState.locked = patch.locked
    }

    if (typeof patch.opacity === 'number' && Number.isFinite(patch.opacity)) {
      nextState.opacity = clamp(patch.opacity, 0.1, 1)
    }

    const nextProfileKey = this.profileKey(nextState.modelId, nextState.modelType)
    if (patch.lipSyncProfile) {
      const profileBase = this.lipSyncProfiles[nextProfileKey]
        ?? (nextProfileKey === previousProfileKey
          ? nextState.lipSyncProfile
          : normalizePetLipSyncProfile())
      nextState.lipSyncProfile = normalizePetLipSyncProfile(
        patch.lipSyncProfile,
        profileBase,
      )
      this.lipSyncProfiles[nextProfileKey] = { ...nextState.lipSyncProfile }
    } else if (nextProfileKey !== previousProfileKey) {
      nextState.lipSyncProfile = this.lipSyncProfiles[nextProfileKey]
        ?? normalizePetLipSyncProfile()
    }

    this.state = nextState
    this.persist()
    return this.getState()
  }

  dockBottomRight(): PetControlState {
    this.state = {
      ...this.state,
      placement: 'bottom-right',
      positionX: null,
      positionY: null,
    }
    this.persist()
    return this.getState()
  }

  place(placement: PetControlState['placement'], displayId?: number | null): PetControlState {
    const patch: PetControlConfigPatch = { placement }
    if (typeof displayId === 'number' && Number.isFinite(displayId)) {
      patch.displayId = Math.trunc(displayId)
    } else if (displayId === null) {
      patch.displayId = null
    }
    return this.applyConfigPatch(patch)
  }

  setVisible(visible: boolean): PetControlState {
    this.state = {
      ...this.state,
      visible,
    }
    this.persist()
    return this.getState()
  }

  setInteractMode(enabled: boolean): PetControlState {
    this.state = {
      ...this.state,
      interactMode: enabled,
    }
    return this.getState()
  }

  applyRendererState(payload: PetRendererStatePayload): PetControlState {
    const placement = isPlacement(payload.placement) ? payload.placement : this.state.placement
    const hasFreePosition = placement === 'free' &&
      typeof payload.positionX === 'number' &&
      Number.isFinite(payload.positionX) &&
      typeof payload.positionY === 'number' &&
      Number.isFinite(payload.positionY)

    const nextModelType = payload.modelType === 'vrm' ? 'vrm' : payload.modelType === 'live2d' ? 'live2d' : this.state.modelType
    const nextModelId = payload.modelId ?? this.state.modelId
    const currentProfileKey = this.profileKey(this.state.modelId, this.state.modelType)
    const nextProfileKey = this.profileKey(nextModelId, nextModelType)
    this.state = {
      ...this.state,
      modelType: nextModelType,
      modelId: nextModelId,
      scale: clamp(payload.scale, MIN_PET_SCALE, MAX_PET_SCALE),
      positionX: hasFreePosition ? payload.positionX : null,
      positionY: hasFreePosition ? payload.positionY : null,
      placement,
      clickThrough: typeof payload.clickThrough === 'boolean' ? payload.clickThrough : this.state.clickThrough,
      locked: typeof payload.locked === 'boolean' ? payload.locked : this.state.locked,
      lipSyncProfile: this.lipSyncProfiles[nextProfileKey]
        ?? (nextProfileKey === currentProfileKey ? this.state.lipSyncProfile : normalizePetLipSyncProfile()),
      ready: payload.ready,
    }
    this.persist()
    return this.getState()
  }

  setReady(ready: boolean): PetControlState {
    this.state = {
      ...this.state,
      ready,
    }
    return this.getState()
  }

  ensureModelId(modelId: string | null): PetControlState {
    if (this.state.modelId === modelId) {
      return this.getState()
    }

    this.state = {
      ...this.state,
      modelId,
      lipSyncProfile: this.lipSyncProfiles[this.profileKey(modelId, this.state.modelType)]
        ?? normalizePetLipSyncProfile(),
    }
    this.persist()
    return this.getState()
  }

  private load(): void {
    try {
      if (!fs.existsSync(this.filePath)) {
        return
      }

      const raw = fs.readFileSync(this.filePath, 'utf8')
      const parsed = JSON.parse(raw) as Partial<PersistedPetState>
      this.lipSyncProfiles = Object.fromEntries(
        Object.entries(parsed.lipSyncProfiles ?? {})
          .filter(([key, profile]) => Boolean(key.trim()) && profile && typeof profile === 'object')
          .map(([key, profile]) => [key, normalizePetLipSyncProfile(profile)]),
      )
      const modelType = parsed.modelType === 'vrm' ? 'vrm' : 'live2d'
      const modelId = typeof parsed.modelId === 'string' ? parsed.modelId : null
      const profileKey = this.profileKey(modelId, modelType)

      this.state = {
        ...DEFAULT_PET_CONTROL_STATE,
        modelType,
        modelId,
        displayId:
          typeof parsed.displayId === 'number' && Number.isFinite(parsed.displayId)
            ? Math.trunc(parsed.displayId)
            : null,
        scale:
          typeof parsed.scale === 'number'
            ? clamp(
                parsed.scale === LEGACY_DEFAULT_PET_SCALE
                  ? PET_SCALE_DEFAULT
                  : parsed.scale,
                MIN_PET_SCALE,
                MAX_PET_SCALE,
              )
            : DEFAULT_PET_CONTROL_STATE.scale,
        positionX: typeof parsed.positionX === 'number' ? parsed.positionX : null,
        positionY: typeof parsed.positionY === 'number' ? parsed.positionY : null,
        placement: isPlacement(parsed.placement) ? parsed.placement : DEFAULT_PET_CONTROL_STATE.placement,
        visible: typeof parsed.visible === 'boolean' ? parsed.visible : DEFAULT_PET_CONTROL_STATE.visible,
        doNotDisturb:
          typeof parsed.doNotDisturb === 'boolean'
            ? parsed.doNotDisturb
            : DEFAULT_PET_CONTROL_STATE.doNotDisturb,
        clickThrough: typeof parsed.clickThrough === 'boolean' ? parsed.clickThrough : DEFAULT_PET_CONTROL_STATE.clickThrough,
        locked: typeof parsed.locked === 'boolean' ? parsed.locked : DEFAULT_PET_CONTROL_STATE.locked,
        opacity:
          typeof parsed.opacity === 'number'
            ? clamp(parsed.opacity, 0.1, 1)
            : DEFAULT_PET_CONTROL_STATE.opacity,
        lipSyncProfile: this.lipSyncProfiles[profileKey] ?? normalizePetLipSyncProfile(),
      }
    } catch (error) {
      logger.warn('[PetStateStore] Failed to load pet state:', error)
      this.state = {
        ...DEFAULT_PET_CONTROL_STATE,
        lipSyncProfile: { ...DEFAULT_PET_CONTROL_STATE.lipSyncProfile },
      }
    }
  }

  private persist(): void {
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true })

      const payload: PersistedPetState = {
        modelType: this.state.modelType,
        modelId: this.state.modelId,
        displayId: this.state.displayId,
        scale: this.state.scale,
        positionX: this.state.positionX,
        positionY: this.state.positionY,
        placement: this.state.placement,
        visible: this.state.visible,
        doNotDisturb: this.state.doNotDisturb,
        clickThrough: this.state.clickThrough,
        locked: this.state.locked,
        opacity: this.state.opacity,
        lipSyncProfiles: this.lipSyncProfiles,
      }

      fs.writeFileSync(this.filePath, JSON.stringify(payload, null, 2), 'utf8')
    } catch (error) {
      logger.warn('[PetStateStore] Failed to persist pet state:', error)
    }
  }

  private profileKey(modelId: string | null, modelType: PetControlState['modelType']): string {
    return modelId?.trim() || `type:${modelType}`
  }
}
