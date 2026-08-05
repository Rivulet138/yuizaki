import { afterEach, describe, expect, it, vi } from 'vitest'
import { petControl } from '../utils/petControl'
import { clearControlAuthToken, CONTROL_ORIGIN } from '../api/clients/http-client'

describe('petControl', () => {
  const setControlToken = (token = 'pet-token') => {
    window.sessionStorage.setItem('yuizaki.control.token', token)
  }

  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    document.querySelectorAll('meta[name="yuizaki-control-token"]').forEach((item) => item.remove())
    window.sessionStorage.clear()
    delete (window as Window & { __YUIZAKI_CONTROL_TOKEN__?: string }).__YUIZAKI_CONTROL_TOKEN__
    delete (window as Window & { petApi?: unknown }).petApi
    window.history.replaceState({}, '', '/')
  })

  it('posts companion idle profile updates to the pet control API', async () => {
    setControlToken()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ success: true }),
    }))

    await petControl.setCompanionIdleProfile({ mood: 'calm', energy: 0.7 })

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/pet/companion-idle-profile'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ mood: 'calm', energy: 0.7 }),
    }))
  })

  it('refreshes the browser control token before calling protected pet APIs', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: vi.fn().mockResolvedValue('<!doctype html><meta name="yuizaki-control-token" content="fresh-token">'),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ activeModelId: null, models: [] }),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(petControl.getCatalog()).resolves.toEqual({ activeModelId: null, models: [] })

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/`, expect.objectContaining({
      cache: 'no-store',
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, expect.stringContaining('/api/pet/catalog'), expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer fresh-token',
      }),
    }))
  })

  it('surfaces pet control API error details', async () => {
    setControlToken()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: vi.fn().mockResolvedValue({ error: 'Pet position is locked' }),
    }))

    await expect(petControl.move(42, 64)).rejects.toThrow('Pet position is locked')
  })

  it('explains missing control authorization in browser mode', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: vi.fn().mockResolvedValue({}),
    }))

    await expect(petControl.getCatalog()).rejects.toThrow('控制服务未授权')
  })

  it('explains missing control authorization when the browser blocks the response', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(petControl.getCatalog()).rejects.toThrow('重新打开界面')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/`, expect.objectContaining({ cache: 'no-store' }))
  })

  it('posts automation motion requests through the HTTP control API', async () => {
    setControlToken()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ success: true }),
    }))

    await petControl.triggerMotion('Idle', 0, { source: 'automation' })

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/pet/animation'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ group: 'Idle', index: 0, source: 'automation' }),
    }))
  })

  it.each(['emotion', 'motion'] as const)('forwards proactive %s cancellation to the HTTP transport', async (kind) => {
    setControlToken()
    const controller = new AbortController()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const pending = kind === 'emotion'
      ? petControl.triggerEmotion('calm', { source: 'automation', signal: controller.signal })
      : petControl.triggerMotion('Idle', 0, { source: 'automation', signal: controller.signal })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal)

    controller.abort()
    await expect(pending).rejects.toThrow()
  })

  it('keeps explicit user emotion and motion actions on the existing IPC path', async () => {
    const triggerEmotion = vi.fn().mockResolvedValue({ success: true })
    const triggerMotion = vi.fn()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        pet: { triggerEmotion },
        live2d: { triggerMotion },
      },
    })

    await petControl.triggerEmotion('calm')
    await petControl.triggerMotion('TapBody', 2)

    expect(triggerEmotion).toHaveBeenCalledWith('calm')
    expect(triggerMotion).toHaveBeenCalledWith('TapBody', 2)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('marks interrupted lip sync stops without changing ordinary stops', async () => {
    setControlToken()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ success: true }),
    }))

    await petControl.stopLipSync()
    await petControl.stopLipSync({ interrupted: true })

    expect(fetch).toHaveBeenNthCalledWith(1, expect.stringContaining('/api/pet/lipsync'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: false }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(2, expect.stringContaining('/api/pet/lipsync'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: false, interrupted: true }),
    }))
  })

  it('persists do-not-disturb through config updates', async () => {
    setControlToken()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ doNotDisturb: true }),
    }))

    await petControl.setDoNotDisturb(true)

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/pet/config'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ doNotDisturb: true }),
    }))
  })

  it('imports local models through Electron IPC when available', async () => {
    const importLocalModelFromPicker = vi.fn().mockResolvedValue({
      success: true,
      canceled: false,
      modelType: 'live2d',
      importedModelId: 'local:hiyori',
      sourcePath: 'C:/models/hiyori',
    })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        pet: {
          importLocalModelFromPicker,
        },
      },
    })

    await petControl.importLocalModelFromPicker('auto')

    expect(importLocalModelFromPicker).toHaveBeenCalledWith('auto')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reads display and placement presets through Electron IPC when available', async () => {
    const getDisplays = vi.fn().mockResolvedValue({ activeDisplayId: 1, displays: [] })
    const getPlacementPresets = vi.fn().mockResolvedValue({ presets: [] })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        pet: {
          getDisplays,
          getPlacementPresets,
        },
      },
    })

    await expect(petControl.getDisplays()).resolves.toEqual({ activeDisplayId: 1, displays: [] })
    await expect(petControl.getPlacementPresets()).resolves.toEqual({ presets: [] })
    expect(getDisplays).toHaveBeenCalledTimes(1)
    expect(getPlacementPresets).toHaveBeenCalledTimes(1)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('updates model placement and transforms through Electron config IPC when available', async () => {
    const updateConfig = vi.fn().mockResolvedValue({ placement: 'free', positionX: 42, positionY: 64 })
    const place = vi.fn().mockResolvedValue({ placement: 'bottom-right', displayId: 2 })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        pet: {
          updateConfig,
          place,
        },
      },
    })

    await expect(petControl.move(42, 64)).resolves.toMatchObject({ placement: 'free', positionX: 42, positionY: 64 })
    await expect(petControl.setScale(0.32)).resolves.toMatchObject({ placement: 'free' })
    await expect(petControl.setOpacity(0.8)).resolves.toMatchObject({ placement: 'free' })
    await expect(petControl.place('bottom-right', 2)).resolves.toMatchObject({ placement: 'bottom-right', displayId: 2 })

    expect(updateConfig).toHaveBeenCalledWith({ positionX: 42, positionY: 64, placement: 'free' })
    expect(updateConfig).toHaveBeenCalledWith({ scale: 0.32 })
    expect(updateConfig).toHaveBeenCalledWith({ opacity: 0.8 })
    expect(place).toHaveBeenCalledWith('bottom-right', 2)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('surfaces Electron IPC delete failures for missing local models', async () => {
    const deleteLocalModel = vi.fn().mockResolvedValue({
      success: false,
      error: 'Local model not found',
    })
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        pet: {
          deleteLocalModel,
        },
      },
    })

    await expect(petControl.deleteLocalModel('local:missing')).rejects.toThrow('Local model not found')
    expect(deleteLocalModel).toHaveBeenCalledWith('local:missing')
  })
})
