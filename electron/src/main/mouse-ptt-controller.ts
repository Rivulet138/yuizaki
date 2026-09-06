import { logger } from './logger'
import type { MouseSideButton } from '../shared/input-bindings'

type MouseEvent = import('uiohook-napi').UiohookMouseEvent

export type MouseHookPort = Pick<typeof import('uiohook-napi').uIOhook, 'on' | 'off' | 'start' | 'stop'>
export type MouseHookLoader = () => Promise<MouseHookPort>

export class MousePttController {
  private hook: MouseHookPort | null = null
  private loading: Promise<boolean> | null = null
  private started = false
  private pressed = false
  private releaseTimer: ReturnType<typeof setTimeout> | null = null
  private activeButton: MouseSideButton | null = null
  private operation = 0
  private lastError: string | null = null
  private downListener: ((event: MouseEvent) => void) | null = null
  private upListener: ((event: MouseEvent) => void) | null = null

  constructor(
    private readonly startVoice: () => void,
    private readonly stopVoice: () => void,
    private readonly loadHook: MouseHookLoader = async () => (await import('uiohook-napi')).uIOhook,
  ) {}

  async start(button: MouseSideButton): Promise<boolean> {
    if (this.started && this.activeButton === button) return true
    if (this.started) this.stop()
    if (this.loading) {
      const pending = this.loading
      const requestedOperation = this.operation
      return pending.then(() => this.operation === requestedOperation ? this.start(button) : false)
    }
    const operation = ++this.operation
    this.lastError = null
    this.loading = this.loadHook().then((uIOhook) => {
      if (operation !== this.operation) return false
      this.hook = uIOhook
      this.activeButton = button
      this.downListener = this.onDown(button)
      this.upListener = this.onUp(button)
      uIOhook.on('mousedown', this.downListener)
      uIOhook.on('mouseup', this.upListener)
      uIOhook.start()
      this.started = true
      return true
    }).catch((error) => {
      this.lastError = error instanceof Error ? error.message : String(error)
      logger.warn(`[MousePttController] failed to start mouse hook: ${this.lastError}`)
      try { this.hook?.stop() } catch (stopError) { logger.warn('[MousePttController] failed to clean up mouse hook:', stopError) }
      this.detach()
      return false
    }).finally(() => { this.loading = null })
    return this.loading
  }

  getError(): string | null {
    return this.lastError
  }

  stop(): void {
    this.operation += 1
    this.release()
    if (!this.hook) return
    try { this.hook.stop() } catch (error) { logger.warn('[MousePttController] failed to stop mouse hook:', error) }
    this.detach()
  }

  release(): void {
    if (!this.pressed) return
    this.pressed = false
    if (this.releaseTimer) clearTimeout(this.releaseTimer)
    this.releaseTimer = null
    this.stopVoice()
  }

  private onDown(button: MouseSideButton) {
    return (event: MouseEvent) => {
      if (Number(event.button) !== button || this.pressed) return
      this.pressed = true
      this.startVoice()
      this.releaseTimer = setTimeout(() => this.release(), 120_000)
    }
  }

  private onUp(button: MouseSideButton) {
    return (event: MouseEvent) => {
      if (Number(event.button) === button) this.release()
    }
  }

  private detach(): void {
    if (!this.hook) return
    if (this.downListener) this.hook.off('mousedown', this.downListener)
    if (this.upListener) this.hook.off('mouseup', this.upListener)
    this.downListener = null
    this.upListener = null
    this.hook = null
    this.activeButton = null
    this.started = false
  }
}
