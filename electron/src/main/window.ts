import { BrowserWindow, screen } from 'electron'
import path from 'path'
import { resolveAppIcon } from './app-icon'
import {
  configureTrustedNavigation,
  resolveTrustedDevServerUrl,
} from './trusted-renderer-url'
import { buildPackagedRendererUrl } from './renderer-protocol'

export interface PetWindowRuntimeOptions {
  controlOrigin: string
  apiOrigin: string
  controlToken: string
  tab?: string
  e2eToken?: string
}

interface PendingRendererMessage {
  channel: string
  args: unknown[]
}

export class PetWindow {
  private mainWindow: BrowserWindow | null = null
  private allowClose = false
  private rendererReady = false
  private pendingRendererMessages: PendingRendererMessage[] = []

  create(runtime?: PetWindowRuntimeOptions, beforeLoad?: (window: BrowserWindow) => void): BrowserWindow {
    if (this.mainWindow) {
      return this.mainWindow
    }

    const workArea = screen.getPrimaryDisplay().workArea
    const width = Math.min(1180, Math.max(760, workArea.width - 80))
    const height = Math.min(780, Math.max(620, workArea.height - 80))

    this.mainWindow = new BrowserWindow({
      width,
      height,
      x: workArea.x + Math.round((workArea.width - width) / 2),
      y: workArea.y + Math.round((workArea.height - height) / 2),
      show: false,
      icon: resolveAppIcon(),
      webPreferences: {
        preload: path.join(__dirname, '../preload/index.js'),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        ...(runtime?.e2eToken ? { additionalArguments: [`--yuizaki-e2e-token=${runtime.e2eToken}`] } : {}),
      },
      transparent: true,
      frame: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      focusable: true,
    })

    configureTrustedNavigation(this.mainWindow.webContents)
    beforeLoad?.(this.mainWindow)

    this.rendererReady = false
    this.mainWindow.webContents.on('did-finish-load', () => {
      this.rendererReady = true
      const messages = this.pendingRendererMessages.splice(0)
      for (const message of messages) {
        this.mainWindow?.webContents.send(message.channel, ...message.args)
      }
    })

    const query = runtime
      ? {
          control_origin: runtime.controlOrigin,
          api_origin: runtime.apiOrigin,
          control_token: runtime.controlToken,
          ...(runtime.tab ? { tab: runtime.tab } : {}),
        }
      : undefined

    const devServerUrl = resolveTrustedDevServerUrl(process.env['VITE_DEV_SERVER_URL'])
    if (devServerUrl) {
      const rendererUrl = new URL(devServerUrl)
      for (const [key, value] of Object.entries(query ?? {})) {
        rendererUrl.searchParams.set(key, value)
      }
      void this.mainWindow.loadURL(rendererUrl.toString())
    } else {
      void this.mainWindow.loadURL(buildPackagedRendererUrl('index.html', query))
    }

    this.mainWindow.on('closed', () => {
      this.mainWindow = null
      this.rendererReady = false
      this.pendingRendererMessages = []
    })

    this.mainWindow.on('close', (event) => {
      if (this.allowClose) {
        return
      }
      event.preventDefault()
      this.hide()
    })

    return this.mainWindow
  }

  get window(): BrowserWindow | null {
    return this.mainWindow
  }

  send(channel: string, ...args: unknown[]): boolean {
    if (!this.mainWindow) {
      return false
    }
    if (!this.rendererReady) {
      this.pendingRendererMessages.push({ channel, args })
      return true
    }
    this.mainWindow.webContents.send(channel, ...args)
    return true
  }

  show(): void {
    if (!this.mainWindow) return
    this.mainWindow.show()
    this.mainWindow.focus()
  }

  hide(): void {
    this.mainWindow?.hide()
  }

  toggle(): void {
    if (this.mainWindow?.isVisible()) {
      this.hide()
    } else {
      this.show()
    }
  }

  close(): void {
    this.allowClose = true
    this.mainWindow?.close()
  }
}
