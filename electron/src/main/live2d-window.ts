import {
  BrowserWindow,
  screen,
  type Event,
  type Rectangle,
  type WebContents,
  type WebContentsConsoleMessageEventParams,
} from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import type {
  AvatarCapabilitySnapshot,
  AvatarCommand,
  AvatarCommandResult,
} from '../shared/avatar-command'
import { AVATAR_COMMAND_DELIVERY_TTL_MS } from '../shared/avatar-command'
import {
  type PetCompanionIdleProfile,
  type PetControlConfigPatch,
  type PetControlState,
  type PetDisplayInfo,
  type PetPlacement,
} from '../shared/pet-control'
import { logger } from './logger'
import { resolveAppIcon } from './app-icon'
import { hasVisibleAlpha } from './pet-alpha-hit-test'
import {
  configureTrustedNavigation,
  resolveTrustedDevServerUrl,
} from './trusted-renderer-url'
import { buildPackagedRendererUrl } from './renderer-protocol'

const getRendererLogPath = (): string =>
  path.join(__dirname, '../../live2d-renderer.log')

let rendererLogBuffer = ''
let rendererLogDroppedEntries = 0
let rendererLogFlushTimer: NodeJS.Timeout | null = null
let rendererLogWriteActive = false
let rendererLogDirectoryReady: Promise<void> | null = null
const RENDERER_LOG_FLUSH_DELAY_MS = 100
const RENDERER_LOG_BUFFER_LIMIT = 256 * 1024

const ensureRendererLogDirectory = (): Promise<void> => {
  if (rendererLogDirectoryReady) return rendererLogDirectoryReady
  const ready = fs.promises
    .mkdir(path.dirname(getRendererLogPath()), { recursive: true })
    .then(() => undefined)
    .catch((error) => {
      rendererLogDirectoryReady = null
      throw error
    })
  rendererLogDirectoryReady = ready
  return ready
}

const scheduleRendererLogFlush = (): void => {
  if (rendererLogFlushTimer || rendererLogWriteActive) return
  rendererLogFlushTimer = setTimeout(flushRendererLog, RENDERER_LOG_FLUSH_DELAY_MS)
}

const flushRendererLog = (): void => {
  if (rendererLogFlushTimer) clearTimeout(rendererLogFlushTimer)
  rendererLogFlushTimer = null
  if (rendererLogWriteActive || (!rendererLogBuffer && rendererLogDroppedEntries === 0)) return

  const dropped = rendererLogDroppedEntries
  const content = `${dropped > 0 ? `[renderer-log] dropped ${dropped} entries while the log writer was busy\n` : ''}${rendererLogBuffer}`
  rendererLogBuffer = ''
  rendererLogDroppedEntries = 0
  rendererLogWriteActive = true

  void ensureRendererLogDirectory()
    .then(() => fs.promises.appendFile(getRendererLogPath(), content, 'utf8'))
    .catch((error) => logger.warn('[Live2DWindow] renderer log write failed:', error))
    .finally(() => {
      rendererLogWriteActive = false
      if (rendererLogBuffer || rendererLogDroppedEntries > 0) scheduleRendererLogFlush()
    })
}

const writeRendererLog = (message: string, payload?: unknown): void => {
  const prefix = `[${new Date().toISOString()}] ${message}`
  const entry =
    payload === undefined
      ? `${prefix}\n`
      : `${prefix} ${JSON.stringify(payload, null, 2)}\n`

  if (rendererLogBuffer.length + entry.length <= RENDERER_LOG_BUFFER_LIMIT) {
    rendererLogBuffer += entry
  } else {
    rendererLogDroppedEntries += 1
  }
  scheduleRendererLogFlush()
}

const TOPMOST_GUARD_INTERVAL_MS = 30000
const RENDERER_RECOVERY_DELAY_MS = 1000
const LIPSYNC_READY_TIMEOUT_MS = 750

type RendererConsoleLevel = 'debug' | 'info' | 'warning' | 'error'

type PetRendererConfigPayload = PetControlConfigPatch

interface PetWindowLayoutResult {
  positionX: number | null
  positionY: number | null
  placement: PetPlacement
  displayId: number
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value))

const normalizeRendererConsoleLevel = (level: unknown): RendererConsoleLevel => {
  if (typeof level === 'number') {
    if (level <= 0) {
      return 'debug'
    }
    if (level === 2) {
      return 'warning'
    }
    if (level >= 3) {
      return 'error'
    }
    return 'info'
  }

  const value = String(level ?? 'info').toLowerCase()
  if (value === 'verbose' || value === 'debug') {
    return 'debug'
  }
  if (value === 'warning' || value === 'warn') {
    return 'warning'
  }
  if (value === 'error') {
    return 'error'
  }
  return 'info'
}

const logRendererConsoleMessage = (
  levelName: RendererConsoleLevel,
  message: string,
  sourceId: string,
  lineNumber: number,
): void => {
  const line = `[Live2DRenderer:${levelName}] ${message} (${sourceId}:${lineNumber})`
  if (levelName === 'error') {
    logger.error(line)
    return
  }
  if (levelName === 'warning') {
    logger.warn(line)
    return
  }
  logger.info(line)
}

export class Live2DWindow {
  private win: BrowserWindow | null = null
  private allowClose = false
  private interactMode = false
  private locked = false
  private clickThrough = true
  private requestedMousePassthrough = false
  private ignoreMouseEvents: boolean | null = null
  private ignoreMouseEventsForward: boolean | null = null
  private rendererReady = false
  private avatarCapabilities: AvatarCapabilitySnapshot | null = null
  private readonly pendingAvatarCommands = new Map<string, {
    resolve: (result: AvatarCommandResult) => void
    sequence: number
    timer: NodeJS.Timeout
  }>()
  private readonly pendingLipSyncStarts = new Map<string, {
    resolve: () => void
    timer: NodeJS.Timeout
  }>()
  private lastPetConfig: PetRendererConfigPayload = {}
  private lastCompanionIdleProfile: PetCompanionIdleProfile | null = null
  private topMostGuardTimer: NodeJS.Timeout | null = null
  private recoveryTimer: NodeJS.Timeout | null = null

  create(controlOrigin = ''): BrowserWindow {
    const primaryDisplay = screen.getPrimaryDisplay()
    const workArea = primaryDisplay.workArea
    const normalizedControlOrigin = controlOrigin.trim().replace(/\/$/, '')

    this.win = new BrowserWindow({
      width: workArea.width,
      height: workArea.height,
      x: workArea.x,
      y: workArea.y,
      show: false,
      icon: resolveAppIcon(),
      webPreferences: {
        preload: path.join(__dirname, '../preload/live2d-preload.js'),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
      },
      transparent: true,
      frame: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      focusable: true,
      hasShadow: false,
      resizable: false,
      movable: false,
      fullscreenable: false,
      backgroundColor: '#00000000',
    })

    this.win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })

    this.applyEffectiveMousePassthrough(true)
    this.rendererReady = false
    this.ensureTopMost()
    configureTrustedNavigation(this.win.webContents)

    const devServerUrl = resolveTrustedDevServerUrl(process.env['VITE_DEV_SERVER_URL'])
    if (devServerUrl) {
      const petWindowUrl = new URL('pet-window.html', devServerUrl)
      if (normalizedControlOrigin) {
        petWindowUrl.searchParams.set('control_origin', normalizedControlOrigin)
      }
      this.win.loadURL(petWindowUrl.toString())
    } else {
      this.win.loadURL(buildPackagedRendererUrl(
        'pet-window.html',
        normalizedControlOrigin ? { control_origin: normalizedControlOrigin } : undefined,
      ))
    }

    writeRendererLog('session-start', {
      mode: devServerUrl ? 'dev' : 'prod',
      url: devServerUrl
        ? new URL('pet-window.html', devServerUrl).toString()
        : buildPackagedRendererUrl('pet-window.html'),
      controlOrigin: normalizedControlOrigin,
      window: { width: workArea.width, height: workArea.height },
    })

    this.win.webContents.on('did-finish-load', () => {
      logger.info('[Live2DWindow] renderer loaded')
      writeRendererLog('did-finish-load')
      this.setLocked(this.locked)
      this.setClickThrough(this.clickThrough)
    })

    this.win.webContents.on('did-start-navigation', (details) => {
      if (details.isMainFrame && !details.isSameDocument) {
        this.invalidateAvatarRenderer('Pet renderer navigation interrupted the avatar command')
      }
    })

    this.win.webContents.on(
      'did-fail-load',
      (_event, errorCode, errorDescription, validatedURL) => {
        logger.error('[Live2DWindow] failed to load renderer:', {
          errorCode,
          errorDescription,
          validatedURL,
        })
        writeRendererLog('did-fail-load', {
          errorCode,
          errorDescription,
          validatedURL,
        })
        this.scheduleRendererRecovery('did-fail-load')
      },
    )

    this.win.webContents.on('console-message', (details: Event<WebContentsConsoleMessageEventParams>) => {
      const eventDetails = details as Event<WebContentsConsoleMessageEventParams> & Partial<WebContentsConsoleMessageEventParams>
      const levelName = normalizeRendererConsoleLevel(eventDetails.level)
      const message = String(eventDetails.message ?? '')
      const lineNumber = eventDetails.lineNumber ?? 0
      const sourceId = eventDetails.sourceId ?? ''

      logRendererConsoleMessage(levelName, message, sourceId, lineNumber)
      writeRendererLog('console-message', {
        level: levelName,
        message,
        line: lineNumber,
        sourceId,
      })
    })

    this.win.webContents.on('render-process-gone', (_event, details) => {
      logger.error('[Live2DWindow] renderer process gone:', details)
      writeRendererLog('render-process-gone', details)
      this.invalidateAvatarRenderer('Pet renderer process exited before acknowledging the avatar command')
      this.scheduleRendererRecovery('render-process-gone')
    })

    this.win.on('blur', () => {
      this.ensureTopMost()
    })

    this.win.on('closed', () => {
      this.stopTopMostGuard()
      this.stopRendererRecovery()
      this.invalidateAvatarRenderer('Pet window closed before acknowledging the avatar command')
      this.win = null
      this.allowClose = false
    })

    this.win.on('close', (event) => {
      if (this.allowClose) {
        return
      }
      event.preventDefault()
      this.hide()
    })

    return this.win
  }

  get window(): BrowserWindow | null {
    return this.win
  }

  handleRendererReady(sender: WebContents): boolean {
    if (
      !this.win ||
      this.win.isDestroyed() ||
      sender !== this.win.webContents ||
      sender.isDestroyed()
    ) {
      return false
    }

    if (this.rendererReady) {
      return true
    }

    this.rendererReady = true
    if (Object.keys(this.lastPetConfig).length > 0) {
      this.sendToRenderer('pet:apply-config', this.lastPetConfig)
    }
    if (this.lastCompanionIdleProfile) {
      this.sendToRenderer('pet:companion-idle-profile', this.lastCompanionIdleProfile)
    }
    this.sendToRenderer('pet:interact-toggle', this.interactMode)
    this.sendToRenderer('pet:request-avatar-capabilities')
    this.requestPetState()
    return true
  }

  handleAvatarCapabilities(sender: WebContents, payload: unknown): boolean {
    if (!this.isCurrentRenderer(sender)) return false
    if (payload === null) {
      this.avatarCapabilities = null
      return true
    }
    if (typeof payload !== 'object') return false
    this.avatarCapabilities = payload as AvatarCapabilitySnapshot
    return true
  }

  handleAvatarCommandResult(sender: WebContents, payload: unknown): boolean {
    if (!this.isCurrentRenderer(sender) || !payload || typeof payload !== 'object') return false
    const result = payload as AvatarCommandResult
    if (typeof result.commandId !== 'string') return false
    const pending = this.pendingAvatarCommands.get(result.commandId)
    if (!pending || result.sequence !== pending.sequence) return false
    clearTimeout(pending.timer)
    this.pendingAvatarCommands.delete(result.commandId)
    pending.resolve(result)
    return true
  }

  getAvatarCapabilities(): AvatarCapabilitySnapshot | null {
    return this.avatarCapabilities
  }

  requestAvatarCapabilities(): void {
    this.sendToRenderer('pet:request-avatar-capabilities')
  }

  startLipSync(audioUrl: string): Promise<void> {
    if (!this.rendererReady || !this.win || this.win.isDestroyed() || this.win.webContents.isDestroyed()) {
      return Promise.resolve()
    }

    const requestId = `lipsync_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pendingLipSyncStarts.delete(requestId)
        resolve()
      }, LIPSYNC_READY_TIMEOUT_MS)
      this.pendingLipSyncStarts.set(requestId, { resolve, timer })
      this.sendToRenderer('pet:lipsync-start', { audioUrl, requestId })
    })
  }

  handleLipSyncReady(sender: WebContents, payload: unknown): boolean {
    if (!this.isCurrentRenderer(sender) || !payload || typeof payload !== 'object') return false
    const requestId = (payload as { requestId?: unknown }).requestId
    if (typeof requestId !== 'string') return false
    const pending = this.pendingLipSyncStarts.get(requestId)
    if (!pending) return false
    clearTimeout(pending.timer)
    this.pendingLipSyncStarts.delete(requestId)
    pending.resolve()
    return true
  }

  sendAvatarCommand(command: AvatarCommand): Promise<AvatarCommandResult> {
    if (!this.rendererReady || !this.win || this.win.isDestroyed() || this.win.webContents.isDestroyed()) {
      return Promise.resolve({
        commandId: command.id,
        sequence: command.sequence,
        status: 'rejected',
        message: 'Pet renderer is not ready',
        at: Date.now(),
      })
    }
    if (this.pendingAvatarCommands.has(command.id)) {
      return Promise.resolve({
        commandId: command.id,
        sequence: command.sequence,
        status: 'rejected',
        message: 'Avatar command id is already pending',
        at: Date.now(),
      })
    }

    return new Promise((resolve) => {
      const deliveryCommand: AvatarCommand = {
        ...command,
        expiresAt: Math.min(
          command.expiresAt ?? Number.POSITIVE_INFINITY,
          Date.now() + AVATAR_COMMAND_DELIVERY_TTL_MS,
        ),
      }
      const timer = setTimeout(() => {
        this.pendingAvatarCommands.delete(command.id)
        resolve({
          commandId: command.id,
          sequence: command.sequence,
          status: 'timeout',
          message: 'Pet renderer acknowledgement timed out; command delivery is unknown',
          at: Date.now(),
        })
      }, 1200)
      this.pendingAvatarCommands.set(command.id, { resolve, sequence: command.sequence, timer })
      this.sendToRenderer('pet:avatar-command', deliveryCommand)
    })
  }

  private isCurrentRenderer(sender: WebContents): boolean {
    return Boolean(
      this.win
      && !this.win.isDestroyed()
      && sender === this.win.webContents
      && !sender.isDestroyed(),
    )
  }

  private invalidateAvatarRenderer(message: string): void {
    this.rendererReady = false
    this.avatarCapabilities = null
    for (const [requestId, pending] of this.pendingLipSyncStarts) {
      clearTimeout(pending.timer)
      this.pendingLipSyncStarts.delete(requestId)
      pending.resolve()
    }
    const at = Date.now()
    for (const [commandId, pending] of this.pendingAvatarCommands) {
      clearTimeout(pending.timer)
      this.pendingAvatarCommands.delete(commandId)
      pending.resolve({
        commandId,
        sequence: pending.sequence,
        status: 'dropped',
        message,
        at,
      })
    }
  }

  get isInteracting(): boolean {
    return this.interactMode
  }

  toggleInteract(): boolean {
    this.interactMode = !this.interactMode
    this.lastPetConfig = {
      ...this.lastPetConfig,
      interactMode: this.interactMode,
    }

    if (this.rendererReady) {
      this.sendToRenderer('pet:interact-toggle', this.interactMode)
    }

    return this.interactMode
  }

  setInteractMode(enabled: boolean): void {
    this.interactMode = Boolean(enabled)
    this.lastPetConfig = {
      ...this.lastPetConfig,
      interactMode: this.interactMode,
    }

    if (this.rendererReady) {
      this.sendToRenderer('pet:interact-toggle', this.interactMode)
    }
  }

  setLocked(enabled: boolean): void {
    this.locked = Boolean(enabled)
    this.lastPetConfig = {
      ...this.lastPetConfig,
      locked: this.locked,
    }
    this.sendToRenderer('pet:apply-config', { locked: this.locked })
  }

  get isLocked(): boolean {
    return this.locked
  }

  setClickThrough(enabled: boolean): void {
    this.clickThrough = Boolean(enabled)
    if (!this.clickThrough) {
      this.requestedMousePassthrough = false
    }
    this.lastPetConfig = {
      ...this.lastPetConfig,
      clickThrough: this.clickThrough,
    }
    this.applyEffectiveMousePassthrough(true)
    this.sendToRenderer('pet:apply-config', { clickThrough: this.clickThrough })
  }

  get isClickThrough(): boolean {
    return this.clickThrough
  }

  setMousePassthrough(ignore: boolean, forward = true): void {
    this.requestedMousePassthrough = Boolean(ignore)
    this.applyEffectiveMousePassthrough(forward)
  }

  private applyEffectiveMousePassthrough(forward = true): void {
    if (!this.win || this.win.isDestroyed()) {
      return
    }

    const shouldIgnore = this.clickThrough || this.requestedMousePassthrough
    const shouldForward = shouldIgnore ? Boolean(forward) : false

    if (this.ignoreMouseEvents === shouldIgnore && this.ignoreMouseEventsForward === shouldForward) {
      return
    }

    this.win.setIgnoreMouseEvents(
      shouldIgnore,
      shouldIgnore ? { forward: shouldForward } : undefined,
    )

    this.ignoreMouseEvents = shouldIgnore
    this.ignoreMouseEventsForward = shouldForward

    writeRendererLog('mouse-passthrough', {
      ignore: shouldIgnore,
      forward: shouldForward,
      interactMode: this.interactMode,
      clickThrough: this.clickThrough,
      locked: this.locked,
    })
  }

  moveTo(x?: number, y?: number, duration: number = 300): { x: number; y: number } | null {
    if (!this.win || this.win.isDestroyed()) {
      return null
    }

    const bounds = this.win.getBounds()
    if (this.locked) {
      return { x: bounds.x, y: bounds.y }
    }
    const targetX = x ?? bounds.x
    const targetY = y ?? bounds.y

    if (duration <= 0) {
      this.win.setBounds({ x: targetX, y: targetY, width: bounds.width, height: bounds.height })
      return { x: targetX, y: targetY }
    }

    const startX = bounds.x
    const startY = bounds.y
    const startTime = Date.now()

    const animate = () => {
      if (!this.win || this.win.isDestroyed()) {
        return
      }

      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = this.easeInOutCubic(progress)

      const currentX = Math.round(startX + (targetX - startX) * eased)
      const currentY = Math.round(startY + (targetY - startY) * eased)

      this.win.setBounds({ x: currentX, y: currentY, width: bounds.width, height: bounds.height })

      if (progress < 1) {
        setTimeout(animate, 16)
      }
    }

    animate()
    return { x: targetX, y: targetY }
  }

  setScale(scale: number): void {
    this.lastPetConfig = {
      ...this.lastPetConfig,
      scale,
    }

    this.sendToRenderer('pet:apply-config', { scale })
  }

  setOpacity(opacity: number): void {
    if (!this.win || this.win.isDestroyed()) {
      return
    }
    this.win.setOpacity(opacity)
    this.sendToRenderer('pet:apply-config', { opacity })
  }

  getDisplays(): PetDisplayInfo[] {
    const primaryId = screen.getPrimaryDisplay().id
    return screen.getAllDisplays()
      .sort((a, b) => a.bounds.x === b.bounds.x ? a.bounds.y - b.bounds.y : a.bounds.x - b.bounds.x)
      .map((display, index) => ({
        id: display.id,
        label: `屏幕 ${index + 1}`,
        primary: display.id === primaryId,
        bounds: {
          x: display.bounds.x,
          y: display.bounds.y,
          width: display.bounds.width,
          height: display.bounds.height,
        },
        workArea: {
          x: display.workArea.x,
          y: display.workArea.y,
          width: display.workArea.width,
          height: display.workArea.height,
        },
      }))
  }

  private easeInOutCubic(t: number): number {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
  }

  show(): void {
    this.win?.show()
    this.ensureTopMost()
    this.startTopMostGuard()
  }

  hide(): void {
    this.stopTopMostGuard()
    this.win?.hide()
  }

  close(): void {
    this.stopTopMostGuard()
    this.stopRendererRecovery()
    this.invalidateAvatarRenderer('Pet window closed before acknowledging the avatar command')
    this.allowClose = true
    this.win?.close()
  }

  applyPetConfig(config: PetRendererConfigPayload): void {
    this.lastPetConfig = {
      ...this.lastPetConfig,
      ...config,
    }

    this.sendToRenderer('pet:apply-config', this.lastPetConfig)
  }

  applyCompanionIdleProfile(profile: PetCompanionIdleProfile): void {
    this.lastCompanionIdleProfile = { ...profile }
    this.sendToRenderer('pet:companion-idle-profile', this.lastCompanionIdleProfile)
  }

  applyWindowLayout(state: PetControlState): PetWindowLayoutResult | null {
    if (!this.win || this.win.isDestroyed()) {
      return null
    }

    const currentBounds = this.win.getBounds()
    const displayInfo = this.resolveDisplay(state.displayId)
    const display = displayInfo.workArea
    if (
      currentBounds.x !== display.x ||
      currentBounds.y !== display.y ||
      currentBounds.width !== display.width ||
      currentBounds.height !== display.height
    ) {
      this.win.setBounds({ x: display.x, y: display.y, width: display.width, height: display.height }, false)
    }

    return {
      positionX: state.positionX,
      positionY: state.positionY,
      placement: state.placement,
      displayId: displayInfo.id,
    }
  }

  moveBy(deltaX: number, deltaY: number): { x: number; y: number } | null {
    if (!this.win || this.win.isDestroyed()) {
      return null
    }

    if (!Number.isFinite(deltaX) || !Number.isFinite(deltaY)) {
      const currentBounds = this.win.getBounds()
      return { x: currentBounds.x, y: currentBounds.y }
    }

    const currentBounds = this.win.getBounds()
    if (this.locked) {
      return { x: currentBounds.x, y: currentBounds.y }
    }
    const nextBounds = this.clampBounds(
      currentBounds.x + Math.round(deltaX),
      currentBounds.y + Math.round(deltaY),
      currentBounds.width,
      currentBounds.height,
    )

    if (currentBounds.x !== nextBounds.x || currentBounds.y !== nextBounds.y) {
      this.win.setPosition(nextBounds.x, nextBounds.y, false)
    }

    return { x: nextBounds.x, y: nextBounds.y }
  }

  getBounds(): Rectangle | null {
    if (!this.win || this.win.isDestroyed()) {
      return null
    }

    return this.win.getBounds()
  }

  requestPetState(): void {
    this.sendToRenderer('pet:request-state')
  }

  async hasVisiblePixels(alphaThreshold = 8): Promise<boolean> {
    if (!this.win || this.win.isDestroyed() || !this.win.isVisible()) {
      return false
    }

    const bounds = this.win.getBounds()
    if (bounds.width <= 0 || bounds.height <= 0) {
      return false
    }

    try {
      const image = await this.win.webContents.capturePage({
        x: 0,
        y: 0,
        width: bounds.width,
        height: bounds.height,
      })
      return hasVisibleAlpha(image.toBitmap(), alphaThreshold)
    } catch (error) {
      logger.warn('[Live2DWindow] alpha visibility scan failed:', error)
      return true
    }
  }

  reloadRenderer(): void {
    if (!this.win || this.win.isDestroyed()) {
      return
    }

    this.invalidateAvatarRenderer('Pet renderer reload interrupted the avatar command')
    this.win.webContents.reloadIgnoringCache()
  }

  sendToRenderer(channel: string, data?: unknown): void {
    if (this.win && !this.win.isDestroyed() && this.rendererReady) {
      this.win.webContents.send(channel, data)
    }
  }

  private ensureTopMost(): void {
    if (!this.win || this.win.isDestroyed()) {
      return
    }

    if (!this.win.isAlwaysOnTop()) {
      this.win.setAlwaysOnTop(true, 'screen-saver')
    }
  }

  private startTopMostGuard(): void {
    if (!this.win || this.win.isDestroyed()) {
      return
    }
    this.stopTopMostGuard()
    this.topMostGuardTimer = setInterval(() => {
      this.ensureTopMost()
    }, TOPMOST_GUARD_INTERVAL_MS)
  }

  private stopTopMostGuard(): void {
    if (this.topMostGuardTimer) {
      clearInterval(this.topMostGuardTimer)
      this.topMostGuardTimer = null
    }
  }

  private scheduleRendererRecovery(reason: string): void {
    if (this.allowClose || !this.win || this.win.isDestroyed()) {
      return
    }

    this.stopRendererRecovery()
    this.recoveryTimer = setTimeout(() => {
      this.recoveryTimer = null
      logger.warn(`[Live2DWindow] recovering renderer after ${reason}`)
      writeRendererLog('renderer-recovery', { reason })
      this.reloadRenderer()
    }, RENDERER_RECOVERY_DELAY_MS)
  }

  private stopRendererRecovery(): void {
    if (this.recoveryTimer) {
      clearTimeout(this.recoveryTimer)
      this.recoveryTimer = null
    }
  }

  private clampBounds(x: number, y: number, width: number, height: number): Rectangle {
    const display = screen.getDisplayNearestPoint({
      x: Math.round(x + width / 2),
      y: Math.round(y + height / 2),
    })
    const area = display.workArea

    const minX = area.x
    const maxX = area.x + Math.max(0, area.width - width)
    const minY = area.y
    const maxY = area.y + Math.max(0, area.height - height)

    return {
      x: clamp(Math.round(x), minX, maxX),
      y: clamp(Math.round(y), minY, maxY),
      width,
      height,
    }
  }

  private resolveDisplay(displayId: number | null | undefined) {
    const displays = screen.getAllDisplays()
    if (typeof displayId === 'number' && Number.isFinite(displayId)) {
      const matched = displays.find((display) => display.id === displayId)
      if (matched) {
        return matched
      }
    }
    return screen.getPrimaryDisplay()
  }

}
