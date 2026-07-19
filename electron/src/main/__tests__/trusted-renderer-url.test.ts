import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  assertTrustedIpcSender,
  configureTrustedNavigation,
  isTrustedRendererUrl,
  resolveTrustedDevServerUrl,
} from '../trusted-renderer-url'
import { buildPackagedRendererUrl } from '../renderer-protocol'

const electronMock = vi.hoisted(() => ({
  openExternal: vi.fn(),
}))

vi.mock('electron', () => ({
  shell: {
    openExternal: electronMock.openExternal,
  },
}))

describe('trusted renderer URL policy', () => {
  afterEach(() => {
    delete process.env['VITE_DEV_SERVER_URL']
    electronMock.openExternal.mockClear()
  })

  it('allows packaged app entries and the configured dev origin only', () => {
    process.env['VITE_DEV_SERVER_URL'] = 'http://localhost:5173'
    const panelUrl = buildPackagedRendererUrl('index.html')
    const petUrl = buildPackagedRendererUrl('pet-window.html')

    expect(isTrustedRendererUrl(panelUrl)).toBe(true)
    expect(isTrustedRendererUrl(petUrl)).toBe(true)
    expect(isTrustedRendererUrl('yuizaki-app://renderer/assets/main.js')).toBe(false)
    expect(isTrustedRendererUrl('file:///C:/app/index.html')).toBe(false)
    expect(isTrustedRendererUrl('file:///C:/Windows/Temp/untrusted.html')).toBe(false)
    expect(isTrustedRendererUrl('http://localhost:5173/index.html')).toBe(true)
    expect(isTrustedRendererUrl('http://127.0.0.1:5173/index.html')).toBe(false)
    expect(isTrustedRendererUrl('http://localhost:9999/index.html')).toBe(false)
    expect(isTrustedRendererUrl('https://example.com')).toBe(false)
    expect(isTrustedRendererUrl('javascript:alert(1)')).toBe(false)
  })

  it('rejects non-loopback dev server URLs before attaching privileged preload', () => {
    expect(resolveTrustedDevServerUrl('http://localhost:5173')).toBe('http://localhost:5173/')
    expect(() => resolveTrustedDevServerUrl('https://example.com')).toThrow(/Untrusted renderer dev server URL/)
  })

  it('uses the same exact-origin policy for IPC senders', () => {
    process.env['VITE_DEV_SERVER_URL'] = 'http://localhost:5173'

    expect(() => assertTrustedIpcSender({
      senderFrame: { url: 'http://localhost:5173/index.html' },
      sender: { getURL: () => '' },
    } as never)).not.toThrow()

    expect(() => assertTrustedIpcSender({
      senderFrame: { url: 'http://localhost:9999/index.html' },
      sender: { getURL: () => '' },
    } as never)).toThrow(/Blocked IPC from untrusted renderer/)
  })

  it('blocks untrusted window opens and external navigations inside Electron', () => {
    const webContents = new EventEmitter() as EventEmitter & {
      setWindowOpenHandler: (handler: (details: { url: string }) => { action: 'deny' }) => void
      windowOpenHandler?: (details: { url: string }) => { action: 'deny' }
    }
    webContents.setWindowOpenHandler = (handler) => {
      webContents.windowOpenHandler = handler
    }

    configureTrustedNavigation(webContents as never)

    expect(webContents.windowOpenHandler?.({ url: 'https://example.com' })).toEqual({ action: 'deny' })
    expect(electronMock.openExternal).toHaveBeenCalledWith('https://example.com/')

    const event = { preventDefault: vi.fn() }
    webContents.emit('will-navigate', event, 'https://example.com/page')

    expect(event.preventDefault).toHaveBeenCalled()
    expect(electronMock.openExternal).toHaveBeenCalledWith('https://example.com/page')

    const localEvent = { preventDefault: vi.fn() }
    webContents.emit('will-navigate', localEvent, 'file:///C:/Windows/Temp/untrusted.html')
    expect(localEvent.preventDefault).toHaveBeenCalled()
  })
})
