import { globalShortcut } from 'electron'
import { uIOhook, type UiohookMouseEvent } from 'uiohook-napi'
import { Live2DWindow } from './live2d-window'
import { logger } from './logger'
import {
  DEFAULT_INPUT_BINDINGS,
  normalizeInputBindingSettings,
  type InputBindingRegistrationStatus,
  type InputBindingSettings,
  type KeyboardShortcutAction,
} from '../shared/input-bindings'

export class PetShortcuts {
  private readonly registeredAccelerators = new Set<string>()
  private settings = structuredClone(DEFAULT_INPUT_BINDINGS)
  private mouseHookStarted = false
  private pushToTalkPressed = false

  constructor(
    private readonly live2dWindow: Live2DWindow,
    private readonly toggleLockHandler: () => void,
    private readonly openPanelHandler: () => void,
    private readonly startVoiceHandler: () => void,
    private readonly stopVoiceHandler: () => void,
    private readonly toggleVisionHandler: () => void,
  ) {}

  register(settings: InputBindingSettings = DEFAULT_INPUT_BINDINGS): InputBindingRegistrationStatus {
    this.releasePushToTalk()
    this.unregisterKeyboardShortcuts()
    this.settings = normalizeInputBindingSettings(settings)

    const errors: string[] = []
    const keyboard = {
      interact: this.registerKeyboardShortcut('interact', this.settings.keyboard.interact, () => {
        this.live2dWindow.toggleInteract()
      }, errors),
      lock: this.registerKeyboardShortcut('lock', this.settings.keyboard.lock, this.toggleLockHandler, errors),
      openPanel: this.registerKeyboardShortcut('openPanel', this.settings.keyboard.openPanel, this.openPanelHandler, errors),
      toggleVision: this.registerKeyboardShortcut(
        'toggleVision',
        this.settings.keyboard.toggleVision,
        this.toggleVisionHandler,
        errors,
      ),
    }

    const mouseHookAvailable = this.settings.pushToTalk.enabled
      ? this.startMouseHook(errors)
      : this.stopMouseHook()

    return {
      mouseHookAvailable,
      pushToTalkActive: this.settings.pushToTalk.enabled && mouseHookAvailable,
      keyboard,
      errors,
    }
  }

  unregister(): void {
    this.releasePushToTalk()
    this.unregisterKeyboardShortcuts()
    this.stopMouseHook()
    logger.info('[PetShortcuts] global input bindings unregistered')
  }

  private registerKeyboardShortcut(
    action: KeyboardShortcutAction,
    accelerator: string,
    handler: () => void,
    errors: string[],
  ): boolean {
    if (!accelerator) return false
    let registered: boolean
    try {
      registered = globalShortcut.register(accelerator, handler)
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      const message = `${action} shortcut invalid: ${accelerator} (${detail})`
      errors.push(message)
      logger.warn(`[PetShortcuts] ${message}`)
      return false
    }
    if (registered) {
      this.registeredAccelerators.add(accelerator)
      logger.info(`[PetShortcuts] ${action} shortcut registered: ${accelerator}`)
      return true
    }
    const message = `${action} shortcut unavailable: ${accelerator}`
    errors.push(message)
    logger.warn(`[PetShortcuts] ${message}`)
    return false
  }

  private unregisterKeyboardShortcuts(): void {
    for (const accelerator of this.registeredAccelerators) {
      globalShortcut.unregister(accelerator)
    }
    this.registeredAccelerators.clear()
  }

  private startMouseHook(errors: string[]): boolean {
    if (this.mouseHookStarted) return true
    try {
      uIOhook.on('mousedown', this.handleMouseDown)
      uIOhook.on('mouseup', this.handleMouseUp)
      uIOhook.start()
      this.mouseHookStarted = true
      logger.info(`[PetShortcuts] push-to-talk registered on mouse button ${this.settings.pushToTalk.mouseButton}`)
      return true
    } catch (error) {
      uIOhook.off('mousedown', this.handleMouseDown)
      uIOhook.off('mouseup', this.handleMouseUp)
      const message = error instanceof Error ? error.message : String(error)
      errors.push(`mouse hook unavailable: ${message}`)
      logger.warn(`[PetShortcuts] failed to start mouse hook: ${message}`)
      return false
    }
  }

  private stopMouseHook(): boolean {
    if (!this.mouseHookStarted) return true
    try {
      uIOhook.stop()
    } catch (error) {
      logger.warn('[PetShortcuts] failed to stop mouse hook:', error)
    }
    uIOhook.off('mousedown', this.handleMouseDown)
    uIOhook.off('mouseup', this.handleMouseUp)
    this.mouseHookStarted = false
    return true
  }

  private readonly handleMouseDown = (event: UiohookMouseEvent): void => {
    if (!this.settings.pushToTalk.enabled) return
    if (Number(event.button) !== this.settings.pushToTalk.mouseButton) return
    if (this.pushToTalkPressed) return
    this.pushToTalkPressed = true
    this.startVoiceHandler()
  }

  private readonly handleMouseUp = (event: UiohookMouseEvent): void => {
    if (Number(event.button) !== this.settings.pushToTalk.mouseButton) return
    this.releasePushToTalk()
  }

  private releasePushToTalk(): void {
    if (!this.pushToTalkPressed) return
    this.pushToTalkPressed = false
    this.stopVoiceHandler()
  }
}
