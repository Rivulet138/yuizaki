import type {
  PetCompanionIdleProfile,
  PetControlConfigPatch,
  PetControlTriggerOptions,
  PetDisplayInfo,
  PetExpressionMixPayload,
  PetControlState,
  PetModelCatalogPayload,
  PetPlacement,
  PetPlacementPreset,
  PetModelType,
} from '../../shared/pet-control'
import type {
  LocalModelImportResponse,
  LocalModelPickerImportResponse,
  LocalModelPickerResponse,
  PetModelImportMode,
} from '../../shared/resource-manager'
import type { AvatarCommand, AvatarCommandResult } from '../../shared/avatar-command'
import {
  CONTROL_AUTH_MISSING_MESSAGE,
  CONTROL_ORIGIN,
  getControlAuthHeaders,
  refreshControlTokenFromServer,
} from '../api/clients/http-client'

type PetControlAutomationOptions = PetControlTriggerOptions & {
  signal?: AbortSignal
  eventVersion?: string
}

const getControlOrigin = (): string => {
  const configuredOrigin = CONTROL_ORIGIN.replace(/\/$/, '')
  if (window.location.origin === configuredOrigin) {
    return window.location.origin
  }

  if (window.location.origin === configuredOrigin.replace('localhost', '127.0.0.1')) {
    return window.location.origin
  }

  return configuredOrigin
}

const createControlConnectionError = (error: unknown): Error => {
  const detail = error instanceof Error && error.message ? `（${error.message}）` : ''
  return new Error(`无法连接桌宠控制服务：请确认 Electron 主程序正在运行，并从 Electron 应用入口重新打开界面后重试。${detail}`, { cause: error })
}

const requestJson = async <T>(path: string, init?: RequestInit): Promise<T> => {
  let authHeaders = getControlAuthHeaders()
  let hasAuthHeader = Boolean(authHeaders['Authorization'])
  if (!hasAuthHeader) {
    const refreshedToken = await refreshControlTokenFromServer()
    if (refreshedToken) {
      authHeaders = { Authorization: `Bearer ${refreshedToken}` }
      hasAuthHeader = true
    }
  }
  if (!hasAuthHeader) {
    throw new Error(CONTROL_AUTH_MISSING_MESSAGE)
  }
  let response: Response
  try {
    response = await fetch(`${getControlOrigin()}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...(init?.headers ?? {}),
      },
    })
  } catch (error) {
    if (!hasAuthHeader) {
      throw new Error(CONTROL_AUTH_MISSING_MESSAGE, { cause: error })
    }
    throw createControlConnectionError(error)
  }

  if (response.status === 401) {
    const refreshedToken = await refreshControlTokenFromServer()
    const previousAuthHeader = authHeaders['Authorization'] || ''
    if (refreshedToken && `Bearer ${refreshedToken}` !== previousAuthHeader) {
      authHeaders = { Authorization: `Bearer ${refreshedToken}` }
      hasAuthHeader = true
      try {
        response = await fetch(`${getControlOrigin()}${path}`, {
          ...init,
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders,
            ...(init?.headers ?? {}),
          },
        })
      } catch (error) {
        if (!hasAuthHeader) {
          throw new Error(CONTROL_AUTH_MISSING_MESSAGE, { cause: error })
        }
        throw createControlConnectionError(error)
      }
    }
  }

  if (!response.ok) {
    let detail = ''
    try {
      const payload = await response.json() as { error?: unknown; message?: unknown }
      detail = typeof payload.error === 'string'
        ? payload.error
        : typeof payload.message === 'string'
          ? payload.message
          : ''
    } catch {
      // keep the status-only fallback for non-JSON errors
    }
    if (response.status === 401) {
      detail = CONTROL_AUTH_MISSING_MESSAGE
    }
    throw new Error(detail || `Pet control request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export type PetBehaviorState =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'reacting'
  | 'sleepy'
  | 'waiting'
  | 'curious'
  | 'focused'
  | 'interrupted'

export interface PetDisplaysPayload {
  activeDisplayId: number | null
  displays: PetDisplayInfo[]
}

export interface PetPlacementPresetsPayload {
  presets: PetPlacementPreset[]
}

export interface PetLipSyncStopOptions {
  interrupted?: boolean
}

export interface PetLipSyncStartOptions extends PetControlTriggerOptions {
  signal?: AbortSignal
}

export const petControl = {
  async getState(): Promise<PetControlState> {
    if (window.petApi?.pet?.getState) {
      return window.petApi.pet.getState()
    }

    return requestJson<PetControlState>('/api/pet/state')
  },

  async getCatalog(): Promise<PetModelCatalogPayload> {
    if (window.petApi?.pet?.getCatalog) {
      return window.petApi.pet.getCatalog()
    }

    return requestJson<PetModelCatalogPayload>('/api/pet/catalog')
  },

  async getDisplays(): Promise<PetDisplaysPayload> {
    if (window.petApi?.pet?.getDisplays) {
      return window.petApi.pet.getDisplays()
    }

    return requestJson<PetDisplaysPayload>('/api/pet/displays')
  },

  async getPlacementPresets(): Promise<PetPlacementPresetsPayload> {
    if (window.petApi?.pet?.getPlacementPresets) {
      return window.petApi.pet.getPlacementPresets()
    }

    return requestJson<PetPlacementPresetsPayload>('/api/pet/presets')
  },

  async getModelCatalog(): Promise<PetModelCatalogPayload> {
    return requestJson<PetModelCatalogPayload>('/api/model/catalog')
  },

  async setModel(modelId: string | null): Promise<PetControlState> {
    if (window.petApi?.pet?.setModel) {
      return window.petApi.pet.setModel(modelId)
    }

    return requestJson<PetControlState>('/api/pet/model', {
      method: 'POST',
      body: JSON.stringify({ modelId }),
    })
  },

  async setModelSelection(modelId: string | null, modelType?: PetModelType): Promise<PetControlState> {
    return requestJson<PetControlState>('/api/model/set', {
      method: 'POST',
      body: JSON.stringify({ modelId, modelType }),
    })
  },

  async setModelType(modelType: PetModelType): Promise<PetControlState> {
    if (window.petApi?.pet?.setModelType) {
      return window.petApi.pet.setModelType(modelType)
    }

    return requestJson<PetControlState>('/api/pet/config', {
      method: 'POST',
      body: JSON.stringify({ modelType }),
    })
  },

  async setLocked(locked: boolean): Promise<PetControlState> {
    if (window.petApi?.pet?.setLocked) {
      return window.petApi.pet.setLocked(locked)
    }

    return requestJson<PetControlState>('/api/pet/config', {
      method: 'POST',
      body: JSON.stringify({ locked }),
    })
  },

  async setClickThrough(clickThrough: boolean): Promise<PetControlState> {
    if (window.petApi?.pet?.setClickThrough) {
      return window.petApi.pet.setClickThrough(clickThrough)
    }

    return requestJson<PetControlState>('/api/pet/config', {
      method: 'POST',
      body: JSON.stringify({ clickThrough }),
    })
  },

  async setDoNotDisturb(doNotDisturb: boolean): Promise<PetControlState> {
    return petControl.updateConfig({ doNotDisturb })
  },

  async reloadRenderer(): Promise<void> {
    if (window.petApi?.pet?.reloadRenderer) {
      await window.petApi.pet.reloadRenderer()
      return
    }

    await requestJson<{ success: true }>('/api/pet/reload', {
      method: 'POST',
      body: '{}',
    })
  },

  async setVisible(visible: boolean): Promise<void> {
    if (window.petApi?.pet?.setVisible) {
      await window.petApi.pet.setVisible(visible)
      return
    }

    await requestJson<{ success: true; visible: boolean }>('/api/pet/visibility', {
      method: 'POST',
      body: JSON.stringify({ visible }),
    })
  },

  async triggerEmotion(emotionId: string, options: PetControlAutomationOptions = {}): Promise<void> {
    if (window.petApi?.pet?.triggerEmotion && options.source !== 'automation') {
      const result = await window.petApi.pet.triggerEmotion(emotionId)
      if (!result?.success) {
        throw new Error(`Emotion preset not found: ${emotionId}`)
      }
      return
    }

    await requestJson<{ success: true }>('/api/pet/emotion', {
      method: 'POST',
      body: JSON.stringify({ emotionId, source: options.source }),
      signal: options.signal,
    })
  },

  async updateConfig(patch: PetControlConfigPatch): Promise<PetControlState> {
    if (window.petApi?.pet?.updateConfig) {
      return window.petApi.pet.updateConfig(patch)
    }

    return requestJson<PetControlState>('/api/pet/config', {
      method: 'POST',
      body: JSON.stringify(patch),
    })
  },

  async snapBottomRight(): Promise<PetControlState> {
    if (window.petApi?.pet?.snapBottomRight) {
      return window.petApi.pet.snapBottomRight()
    }

    return requestJson<PetControlState>('/api/pet/dock', {
      method: 'POST',
      body: '{}',
    })
  },

  async place(placement: Exclude<PetPlacement, 'free'>, displayId?: number | null): Promise<PetControlState> {
    if (window.petApi?.pet?.place) {
      return window.petApi.pet.place(placement, displayId)
    }

    return requestJson<PetControlState>('/api/pet/place', {
      method: 'POST',
      body: JSON.stringify({ placement, displayId }),
    })
  },

  async setScale(scale: number): Promise<PetControlState> {
    if (window.petApi?.pet?.updateConfig) {
      return window.petApi.pet.updateConfig({ scale })
    }

    const result = await requestJson<{ success: true; state: PetControlState }>('/api/pet/scale', {
      method: 'POST',
      body: JSON.stringify({ scale }),
    })
    return result.state
  },

  async setOpacity(opacity: number): Promise<PetControlState> {
    if (window.petApi?.pet?.updateConfig) {
      return window.petApi.pet.updateConfig({ opacity })
    }

    const result = await requestJson<{ success: true; state: PetControlState }>('/api/pet/opacity', {
      method: 'POST',
      body: JSON.stringify({ opacity }),
    })
    return result.state
  },

  async setInteractMode(enabled: boolean): Promise<PetControlState> {
    if (window.petApi?.pet?.setInteractMode) {
      return window.petApi.pet.setInteractMode(enabled)
    }

    return requestJson<PetControlState>('/api/pet/interact', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    })
  },

  async triggerMotion(group: string, index: number = 0, options: PetControlAutomationOptions = {}): Promise<void> {
    if (window.petApi?.live2d?.triggerMotion && options.source !== 'automation') {
      window.petApi.live2d.triggerMotion(group, index)
      return
    }

    await requestJson<{ success: true }>('/api/pet/animation', {
      method: 'POST',
      body: JSON.stringify({ group, index, source: options.source }),
      signal: options.signal,
    })
  },

  async triggerExpression(name: string, options: PetControlTriggerOptions = {}): Promise<void> {
    if (window.petApi?.live2d?.triggerExpression && options.source !== 'automation') {
      window.petApi.live2d.triggerExpression(name)
      return
    }

    await requestJson<{ success: true }>('/api/pet/expression', {
      method: 'POST',
      body: JSON.stringify({ name, source: options.source }),
    })
  },

  async triggerExpressionMix(payload: PetExpressionMixPayload, options: PetControlTriggerOptions = {}): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/expression-mix', {
      method: 'POST',
      body: JSON.stringify({ ...payload, source: options.source }),
    })
  },

  async triggerAvatarCommand(command: AvatarCommand, options: PetControlAutomationOptions = {}): Promise<AvatarCommandResult> {
    return requestJson<{ success: boolean; result: AvatarCommandResult }>('/api/pet/avatar-command', {
      method: 'POST',
      body: JSON.stringify({ command, source: options.source }),
      signal: options.signal,
    }).then((payload) => payload.result)
  },

  async triggerParameterOverrides(payload: PetExpressionMixPayload, options: PetControlTriggerOptions = {}): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/expression-mix', {
      method: 'POST',
      body: JSON.stringify({ ...payload, source: options.source }),
    })
  },

  async move(x: number, y: number): Promise<PetControlState> {
    if (window.petApi?.pet?.updateConfig) {
      return window.petApi.pet.updateConfig({ positionX: x, positionY: y, placement: 'free' })
    }

    const result = await requestJson<{ success: true; state: PetControlState }>('/api/pet/move', {
      method: 'POST',
      body: JSON.stringify({ x, y }),
    })
    return result.state
  },

  async setBehaviorState(state: PetBehaviorState, durationMs?: number, options: PetControlTriggerOptions = {}): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/behavior-state', {
      method: 'POST',
      body: JSON.stringify({ state, durationMs, source: options.source }),
    })
  },

  async updateCompanionIdleProfile(profile: PetCompanionIdleProfile): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/companion-idle-profile', {
      method: 'POST',
      body: JSON.stringify(profile),
    })
  },

  async setCompanionIdleProfile(profile: PetCompanionIdleProfile): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/companion-idle-profile', {
      method: 'POST',
      body: JSON.stringify(profile),
    })
  },

  async startLipSync(audioUrl: string, options: PetLipSyncStartOptions = {}): Promise<void> {
    await requestJson<{ success: true }>('/api/pet/lipsync', {
      method: 'POST',
      body: JSON.stringify({ audioUrl, enabled: true, source: options.source }),
      signal: options.signal,
    })
  },

  async stopLipSync(options: PetLipSyncStopOptions = {}): Promise<void> {
    const body = options.interrupted === true
      ? { enabled: false, interrupted: true }
      : { enabled: false }
    await requestJson<{ success: true }>('/api/pet/lipsync', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  async pickLocalModel(modelType: PetModelImportMode): Promise<LocalModelPickerResponse> {
    if (window.petApi?.pet?.pickLocalModel) {
      return window.petApi.pet.pickLocalModel(modelType)
    }

    return requestJson<LocalModelPickerResponse>('/api/pet/model/pick', {
      method: 'POST',
      body: JSON.stringify({ modelType }),
    })
  },

  async importLocalModel(sourcePath: string, modelType: PetModelImportMode): Promise<LocalModelImportResponse> {
    if (window.petApi?.pet?.importLocalModel) {
      return window.petApi.pet.importLocalModel(sourcePath, modelType)
    }

    return requestJson<LocalModelImportResponse>('/api/pet/model/import', {
      method: 'POST',
      body: JSON.stringify({ sourcePath, modelType }),
    })
  },

  async importLocalModelFromPicker(modelType: PetModelImportMode): Promise<LocalModelPickerImportResponse> {
    if (window.petApi?.pet?.importLocalModelFromPicker) {
      return window.petApi.pet.importLocalModelFromPicker(modelType)
    }

    return requestJson<LocalModelPickerImportResponse>('/api/pet/model/import-from-picker', {
      method: 'POST',
      body: JSON.stringify({ modelType }),
    })
  },

  async deleteLocalModel(modelId: string): Promise<{ success: true; state: PetControlState; catalog: PetModelCatalogPayload; modelRoots: { live2d: string; vrm: string } }> {
    if (window.petApi?.pet?.deleteLocalModel) {
      const result = await window.petApi.pet.deleteLocalModel(modelId)
      if (!result.success) {
        throw new Error(result.error || 'Local model not found')
      }
      return result
    }

    return requestJson<{ success: true; state: PetControlState; catalog: PetModelCatalogPayload; modelRoots: { live2d: string; vrm: string } }>('/api/pet/model/delete', {
      method: 'POST',
      body: JSON.stringify({ modelId }),
    })
  },
}
