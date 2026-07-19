import { shell, type IpcMainEvent, type IpcMainInvokeEvent, type WebContents } from 'electron'
import {
  PACKAGED_RENDERER_HOST,
  PACKAGED_RENDERER_SCHEME,
  type PackagedRendererEntry,
} from './renderer-protocol'

type IpcSenderEvent = IpcMainEvent | IpcMainInvokeEvent
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

const isLoopbackHost = (hostname: string): boolean =>
  LOOPBACK_HOSTS.has(hostname.toLowerCase())

const TRUSTED_PACKAGED_RENDERER_FILES = new Set<PackagedRendererEntry>([
  'index.html',
  'pet-window.html',
])

const isTrustedPackagedRendererUrl = (url: URL): boolean => {
  if (url.protocol !== `${PACKAGED_RENDERER_SCHEME}:` || url.hostname !== PACKAGED_RENDERER_HOST) {
    return false
  }
  const entry = url.pathname.replace(/^\/+/, '')
  return TRUSTED_PACKAGED_RENDERER_FILES.has(entry as PackagedRendererEntry)
}

const getConfiguredDevOrigin = (): string | null => {
  const value = process.env['VITE_DEV_SERVER_URL']?.trim()
  if (!value) {
    return null
  }
  try {
    const url = new URL(value)
    if ((url.protocol === 'http:' || url.protocol === 'https:') && isLoopbackHost(url.hostname)) {
      return url.origin
    }
  } catch {
    return null
  }
  return null
}

export const isTrustedRendererUrl = (rawUrl: string | null | undefined): boolean => {
  if (!rawUrl) {
    return false
  }

  try {
    const url = new URL(rawUrl)
    if (url.protocol === `${PACKAGED_RENDERER_SCHEME}:`) {
      return isTrustedPackagedRendererUrl(url)
    }
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.origin === getConfiguredDevOrigin()
    }
  } catch {
    return false
  }

  return false
}

export const resolveTrustedDevServerUrl = (rawUrl: string | undefined): string | null => {
  const value = rawUrl?.trim()
  if (!value) {
    return null
  }
  try {
    const url = new URL(value)
    if ((url.protocol !== 'http:' && url.protocol !== 'https:') || !isLoopbackHost(url.hostname)) {
      throw new Error(`Untrusted renderer dev server URL: ${value}`)
    }
    return url.toString()
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Untrusted renderer dev server URL:')) {
      throw error
    }
    throw Object.assign(new Error(`Untrusted renderer dev server URL: ${value}`), { cause: error })
  }
}

export const assertTrustedIpcSender = (event: IpcSenderEvent): void => {
  const senderUrl = event.senderFrame?.url || event.sender.getURL()
  if (!isTrustedRendererUrl(senderUrl)) {
    throw new Error(`Blocked IPC from untrusted renderer: ${senderUrl || 'unknown'}`)
  }
}

const openExternalWebUrl = async (rawUrl: string): Promise<void> => {
  try {
    const url = new URL(rawUrl)
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      await shell.openExternal(url.toString())
    }
  } catch {
    // Ignore malformed navigation targets.
  }
}

export const configureTrustedNavigation = (webContents: WebContents): void => {
  webContents.setWindowOpenHandler(({ url }) => {
    void openExternalWebUrl(url)
    return { action: 'deny' }
  })

  webContents.on('will-navigate', (event, url) => {
    if (isTrustedRendererUrl(url)) {
      return
    }
    event.preventDefault()
    void openExternalWebUrl(url)
  })
}
