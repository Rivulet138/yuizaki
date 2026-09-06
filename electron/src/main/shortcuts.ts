import { globalShortcut } from 'electron'
import { Live2DWindow } from './live2d-window'
import { logger } from './logger'
import { MousePttController } from './mouse-ptt-controller'
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
  private readonly mousePtt: MousePttController
  private keyboardStatus: InputBindingRegistrationStatus['keyboard'] = {
    interact: false,
    lock: false,
    openPanel: false,
    toggleVision: false,
    emergencyStop: false,
  }

  constructor(
    private readonly live2dWindow: Live2DWindow,
    private readonly toggleLockHandler: () => void,
    private readonly openPanelHandler: () => void,
    startVoiceHandler: () => void,
    stopVoiceHandler: () => void,
    private readonly toggleVisionHandler: () => void,
    private readonly emergencyStopHandler: () => void,
  ) {
    this.mousePtt = new MousePttController(startVoiceHandler, stopVoiceHandler)
  }

  register(settings: InputBindingSettings = DEFAULT_INPUT_BINDINGS): InputBindingRegistrationStatus {
    this.mousePtt.release()
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
      emergencyStop: this.registerKeyboardShortcut(
        'emergencyStop',
        this.settings.keyboard.emergencyStop,
        this.emergencyStopHandler,
        errors,
      ),
    }
    this.keyboardStatus = keyboard

    // Loading the native hook is asynchronous and only occurs after explicit opt-in.
    const mouseHookAvailable = false
    if (this.settings.pushToTalk.enabled) {
      void this.mousePtt.start(this.settings.pushToTalk.mouseButton).then((available) => {
        if (available) logger.info(`[PetShortcuts] push-to-talk registered on mouse button ${this.settings.pushToTalk.mouseButton}`)
      })
    } else this.mousePtt.stop()

    return {
      mouseHookAvailable,
      pushToTalkActive: this.settings.pushToTalk.enabled && mouseHookAvailable,
      keyboard,
      errors,
    }
  }

  async waitForMouseHook(): Promise<InputBindingRegistrationStatus> {
    const mouseHookAvailable = this.settings.pushToTalk.enabled
      ? await this.mousePtt.start(this.settings.pushToTalk.mouseButton)
      : false
    return {
      mouseHookAvailable,
      pushToTalkActive: this.settings.pushToTalk.enabled && mouseHookAvailable,
      keyboard: { ...this.keyboardStatus },
      errors: mouseHookAvailable || !this.settings.pushToTalk.enabled
        ? []
        : [`mouse hook unavailable${this.mousePtt.getError() ? `: ${this.mousePtt.getError()}` : ''}`],
    }
  }

  unregister(): void {
    this.mousePtt.release()
    this.unregisterKeyboardShortcuts()
    this.mousePtt.stop()
    logger.info('[PetShortcuts] global input bindings unregistered')
  }

  releasePushToTalk(): void {
    this.mousePtt.release()
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

}
