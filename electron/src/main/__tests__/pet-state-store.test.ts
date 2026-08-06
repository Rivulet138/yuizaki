import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { app } from 'electron'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PetStateStore } from '../pet-state-store'

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => os.tmpdir()),
  },
}))

describe('PetStateStore', () => {
  let userDataDir = ''

  beforeEach(() => {
    userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-pet-state-'))
    vi.mocked(app.getPath).mockReturnValue(userDataDir)
  })

  afterEach(() => {
    fs.rmSync(userDataDir, { recursive: true, force: true })
  })

  it('restores the last selected Live2D or VRM model after a restart', () => {
    const firstStore = new PetStateStore()

    firstStore.applyConfigPatch({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
      scale: 0.42,
      visible: false,
    })

    const persisted = JSON.parse(fs.readFileSync(path.join(userDataDir, 'pet-state.json'), 'utf8')) as Record<string, unknown>
    expect(persisted).toEqual(expect.objectContaining({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
      scale: 0.42,
      visible: false,
    }))

    const restoredStore = new PetStateStore()

    expect(restoredStore.getState()).toEqual(expect.objectContaining({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
      scale: 0.42,
      visible: false,
    }))
  })

  it('persists renderer free-position updates without turning docked presets into 0,0', () => {
    const store = new PetStateStore()

    store.applyRendererState({
      modelType: 'live2d',
      modelId: 'llm-live2d/yumi',
      scale: 0.31,
      positionX: null,
      positionY: null,
      placement: 'bottom-right',
      ready: true,
    })

    expect(store.getState()).toEqual(expect.objectContaining({
      placement: 'bottom-right',
      positionX: null,
      positionY: null,
      ready: true,
    }))

    store.applyRendererState({
      modelType: 'live2d',
      modelId: 'llm-live2d/yumi',
      scale: 0.31,
      positionX: 420,
      positionY: 680,
      placement: 'free',
      ready: true,
    })

    expect(store.getState()).toEqual(expect.objectContaining({
      placement: 'free',
      positionX: 420,
      positionY: 680,
    }))
  })

  it('keeps lip-sync calibration isolated per model and restores it after restart', () => {
    const store = new PetStateStore()

    store.applyConfigPatch({
      modelId: 'live2d:a',
      modelType: 'live2d',
      lipSyncProfile: { gain: 7.5, attack: 0.7 },
    })
    store.applyConfigPatch({
      modelId: 'live2d:b',
      lipSyncProfile: { gain: 2.5 },
    })

    expect(store.getState().lipSyncProfile).toEqual(expect.objectContaining({
      gain: 2.5,
      attack: 0.42,
    }))

    store.applyConfigPatch({ modelId: 'live2d:a' })
    expect(store.getState().lipSyncProfile).toEqual(expect.objectContaining({
      gain: 7.5,
      attack: 0.7,
    }))

    const restoredStore = new PetStateStore()
    expect(restoredStore.getState().lipSyncProfile).toEqual(expect.objectContaining({
      gain: 7.5,
      attack: 0.7,
    }))
  })

  it('clamps lip-sync calibration and does not expose mutable state references', () => {
    const store = new PetStateStore()
    const next = store.applyConfigPatch({
      modelId: 'live2d:a',
      lipSyncProfile: {
        gain: 99,
        noiseGate: -1,
        maxOpen: 4,
        attack: 0,
        release: 2,
      },
    })

    expect(next.lipSyncProfile).toEqual({
      gain: 12,
      noiseGate: 0,
      maxOpen: 1,
      attack: 0.05,
      release: 1,
    })

    next.lipSyncProfile.gain = 0.5
    expect(store.getState().lipSyncProfile.gain).toBe(12)
  })
})
