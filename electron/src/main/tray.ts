import { Menu, Tray, app, nativeImage, shell } from 'electron'
import fs from 'fs'
import path from 'path'
import { Live2DWindow } from './live2d-window'
import { logger } from './logger'
import type { PetControlState } from '../shared/pet-control'

export class PetTray {
  private tray: Tray | null = null
  private openPanelHandler: ((tab?: string) => Promise<void> | void) | null = null
  private dockBottomRightHandler: (() => void) | null = null
  private toggleInteractHandler: (() => void) | null = null
  private toggleLockHandler: (() => void) | null = null
  private toggleClickThroughHandler: (() => void) | null = null
  private setVisibleHandler: ((visible: boolean) => void) | null = null
  private stateResolver: (() => PetControlState) | null = null
  private reloadHandler: (() => void) | null = null
  private toggleVoiceHandler: (() => void) | null = null
  private voiceBindingLabel = '按住鼠标侧键 2 说话'
  private voiceBindingAvailable = false

  create(
    live2dWindow: Live2DWindow,
    openPanelHandler: (tab?: string) => Promise<void> | void,
    dockBottomRightHandler: () => void,
    toggleInteractHandler: () => void,
    toggleLockHandler: () => void,
    toggleClickThroughHandler: () => void,
    setVisibleHandler: (visible: boolean) => void,
    stateResolver: () => PetControlState,
    reloadHandler: () => void,
    toggleVoiceHandler?: () => void,
    voiceBinding?: { label: string; available: boolean },
  ): Tray {
    const icon = this.resolveTrayIcon()

    this.tray = new Tray(icon)
    this.openPanelHandler = openPanelHandler
    this.dockBottomRightHandler = dockBottomRightHandler
    this.toggleInteractHandler = toggleInteractHandler
    this.toggleLockHandler = toggleLockHandler
    this.toggleClickThroughHandler = toggleClickThroughHandler
    this.setVisibleHandler = setVisibleHandler
    this.stateResolver = stateResolver
    this.reloadHandler = reloadHandler
    this.toggleVoiceHandler = toggleVoiceHandler ?? null
    this.voiceBindingLabel = voiceBinding?.label ?? this.voiceBindingLabel
    this.voiceBindingAvailable = voiceBinding?.available ?? false

    this.refreshMenu(live2dWindow)
    this.tray.setToolTip('Yuizaki')

    this.tray.on('click', () => {
      void this.openControlPanel('pet')
    })

    return this.tray
  }

  refresh(live2dWindow?: Live2DWindow): void {
    if (!this.tray || !live2dWindow) {
      return
    }
    this.refreshMenu(live2dWindow)
  }

  setVoiceBindingStatus(label: string, available: boolean, live2dWindow?: Live2DWindow): void {
    this.voiceBindingLabel = label
    this.voiceBindingAvailable = available
    this.refresh(live2dWindow)
  }

  private refreshMenu(live2dWindow: Live2DWindow): void {
    if (!this.tray) {
      return
    }

    const state = this.stateResolver?.()
    const contextMenu = Menu.buildFromTemplate([
      {
        label: '打开控制面板',
        click: () => {
          void this.openControlPanel('pet')
        },
      },
      {
        label: '打开对话中心',
        click: () => {
          void this.openControlPanel('chat')
        },
      },
      {
        label: live2dWindow.window?.isVisible() ? '隐藏桌宠' : '显示桌宠',
        click: () => {
          this.setVisibleHandler?.(!live2dWindow.window?.isVisible())
          this.refreshMenu(live2dWindow)
        },
      },
      {
        label: '切换拖动模式',
        type: 'checkbox',
        checked: Boolean(state?.interactMode),
        click: () => {
          this.toggleInteractHandler?.()
          this.refreshMenu(live2dWindow)
        },
      },
      {
        label: '鼠标穿透',
        type: 'checkbox',
        checked: Boolean(state?.clickThrough),
        click: () => {
          this.toggleClickThroughHandler?.()
          this.refreshMenu(live2dWindow)
        },
      },
      {
        label: '锁定位置',
        type: 'checkbox',
        checked: Boolean(state?.locked),
        click: () => {
          this.toggleLockHandler?.()
          this.refreshMenu(live2dWindow)
        },
      },
      {
        label: '贴到右下角',
        click: () => {
          this.dockBottomRightHandler?.()
          this.refreshMenu(live2dWindow)
        },
      },
      {
        label: '重新加载 Live2D',
        click: () => {
          this.reloadHandler?.()
        },
      },
      {
        label: this.voiceBindingAvailable
          ? `语音对话（${this.voiceBindingLabel}）`
          : `语音对话（${this.voiceBindingLabel}，不可用）`,
        click: () => {
          this.toggleVoiceHandler?.()
        },
      },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          app.quit()
        },
      },
    ])

    this.tray.setContextMenu(contextMenu)
  }

  private async openControlPanel(tab?: string): Promise<void> {
    if (this.openPanelHandler) {
      await this.openPanelHandler(tab)
      return
    }
    await shell.openExternal('http://localhost:38945/')
  }

  private resolveTrayIcon() {
    const iconCandidates = [
      path.join(__dirname, '../../assets/yuizaki-ribbon-icon.png'),
      path.join(process.cwd(), 'assets/yuizaki-ribbon-icon.png'),
    ]

    for (const iconPath of iconCandidates) {
      if (!fs.existsSync(iconPath)) {
        continue
      }

      const icon = nativeImage.createFromPath(iconPath)
      if (!icon.isEmpty()) {
        return icon
      }

      logger.warn('[PetTray] icon exists but failed to load:', iconPath)
    }

    logger.warn('[PetTray] all icon candidates failed, using empty fallback')
    return nativeImage.createEmpty()
  }

  destroy(): void {
    if (this.tray) {
      this.tray.destroy()
      this.tray = null
    }
  }
}
