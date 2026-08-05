export interface DragState {
  dragLastScreen: { x: number; y: number } | null
  dragLastClient: { x: number; y: number } | null
}

export interface MouseMoveContext {
  isDraggingWindow: boolean
  dragLastScreen: { x: number; y: number } | null
  dragLastClient: { x: number; y: number } | null
}

export interface MouseDownContext {
  button: number
  clientX: number
  clientY: number
}

export interface MouseUpContext {
  button: number
  moved: boolean
  mouseDownOnModel: boolean
  isDraggingWindow: boolean
}

export interface ContextMenuContext {
  hasPoint: boolean
  insideInteractionArea: boolean
}

export interface WheelContext {
  isDraggingWindow: boolean
  buttons: number
  hasPoint: boolean
  insideInteractionArea: boolean
  currentScale: number
  minScale: number
  maxScale: number
  deltaY: number
}

export interface MouseLeaveContext {
  isDraggingWindow: boolean
}

export interface DragEndResult {
  shouldFinish: boolean
  nextDragCooldownUntil: number
  nextDragMoved: false
  nextModelHovering: false
  draggedAt: number
}

export interface DragDeltaResult {
  deltaX: number
  deltaY: number
  nextScreen: { x: number; y: number }
  nextClient: { x: number; y: number }
}

export interface AlphaHitTestPoint {
  x: number
  y: number
}

export const DEFAULT_ALPHA_HIT_TEST_INTERVAL_MS = 250

export interface AlphaHitTestSchedulerOptions {
  execute: (point: AlphaHitTestPoint) => Promise<boolean>
  onResult: (visible: boolean, point: AlphaHitTestPoint) => void
  onError?: (error: unknown) => void
  intervalMs?: number
  tolerancePx?: number
  now?: () => number
  setTimer?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>
  clearTimer?: (timer: ReturnType<typeof setTimeout>) => void
}

interface PendingAlphaHitTest {
  generation: number
  point: AlphaHitTestPoint
}

export class AlphaHitTestScheduler {
  private readonly execute: AlphaHitTestSchedulerOptions['execute']
  private readonly onResult: AlphaHitTestSchedulerOptions['onResult']
  private readonly onError: NonNullable<AlphaHitTestSchedulerOptions['onError']>
  private readonly intervalMs: number
  private readonly tolerancePx: number
  private readonly now: () => number
  private readonly setTimer: NonNullable<AlphaHitTestSchedulerOptions['setTimer']>
  private readonly clearTimer: NonNullable<AlphaHitTestSchedulerOptions['clearTimer']>
  private generation = 0
  private inFlight = false
  private lastStartedAt = Number.NEGATIVE_INFINITY
  private lastRequestedPoint: AlphaHitTestPoint | null = null
  private pending: PendingAlphaHitTest | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private disposed = false

  constructor(options: AlphaHitTestSchedulerOptions) {
    this.execute = options.execute
    this.onResult = options.onResult
    this.onError = options.onError ?? (() => undefined)
    this.intervalMs = Math.max(0, options.intervalMs ?? DEFAULT_ALPHA_HIT_TEST_INTERVAL_MS)
    this.tolerancePx = Math.max(0, options.tolerancePx ?? 3)
    this.now = options.now ?? Date.now
    this.setTimer = options.setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs))
    this.clearTimer = options.clearTimer ?? ((timer) => clearTimeout(timer))
  }

  request(point: AlphaHitTestPoint): boolean {
    if (this.disposed || this.isNearLastRequest(point)) {
      return false
    }

    this.lastRequestedPoint = { ...point }
    this.pending = { generation: ++this.generation, point: { ...point } }
    this.pump()
    return true
  }

  invalidate(): void {
    this.generation += 1
    this.pending = null
    this.lastRequestedPoint = null
    if (this.timer !== null) {
      this.clearTimer(this.timer)
      this.timer = null
    }
  }

  dispose(): void {
    this.disposed = true
    this.invalidate()
  }

  private isNearLastRequest(point: AlphaHitTestPoint): boolean {
    return Boolean(
      this.lastRequestedPoint
      && Math.abs(this.lastRequestedPoint.x - point.x) <= this.tolerancePx
      && Math.abs(this.lastRequestedPoint.y - point.y) <= this.tolerancePx,
    )
  }

  private pump(): void {
    if (this.disposed || this.inFlight || !this.pending || this.timer !== null) {
      return
    }

    const delayMs = Math.max(0, this.intervalMs - (this.now() - this.lastStartedAt))
    if (delayMs > 0) {
      this.timer = this.setTimer(() => {
        this.timer = null
        this.pump()
      }, delayMs)
      return
    }

    const request = this.pending
    this.pending = null
    this.inFlight = true
    this.lastStartedAt = this.now()

    void Promise.resolve()
      .then(() => this.execute(request.point))
      .then((visible) => {
        if (!this.disposed && request.generation === this.generation) {
          this.onResult(Boolean(visible), request.point)
        }
      })
      .catch((error: unknown) => {
        if (!this.disposed && request.generation === this.generation) {
          this.onError(error)
        }
      })
      .finally(() => {
        this.inFlight = false
        this.pump()
      })
  }
}

export function computeDragDelta(
  state: DragState,
  event: MouseEvent,
): DragDeltaResult | null {
  if (!state.dragLastScreen) {
    return null
  }

  let deltaX = event.screenX - state.dragLastScreen.x
  let deltaY = event.screenY - state.dragLastScreen.y

  if (deltaX === 0 && deltaY === 0 && state.dragLastClient) {
    deltaX = event.clientX - state.dragLastClient.x
    deltaY = event.clientY - state.dragLastClient.y
  }

  if (deltaX === 0 && deltaY === 0) {
    return null
  }

  return {
    deltaX,
    deltaY,
    nextScreen: { x: event.screenX, y: event.screenY },
    nextClient: { x: event.clientX, y: event.clientY },
  }
}

export function shouldMouseUpTriggerClick(options: {
  button: number
  mouseDownOnModel: boolean
  moved: boolean
  isDraggingWindow: boolean
}): boolean {
  return (
    options.button === 0 &&
    options.mouseDownOnModel &&
    !options.moved &&
    !options.isDraggingWindow
  )
}

export function resolveMouseMove(context: MouseMoveContext, event: MouseEvent): DragDeltaResult | null {
  if (!context.isDraggingWindow || !context.dragLastScreen) {
    return null
  }

  return computeDragDelta(
    {
      dragLastScreen: context.dragLastScreen,
      dragLastClient: context.dragLastClient,
    },
    event,
  )
}

export function resolveMouseUp(context: MouseUpContext): boolean {
  return shouldMouseUpTriggerClick({
    button: context.button,
    mouseDownOnModel: context.mouseDownOnModel,
    moved: context.moved,
    isDraggingWindow: context.isDraggingWindow,
  })
}

export function resolveMouseDown(context: MouseDownContext):
  | { shouldIgnore: true }
  | {
      shouldIgnore: false
      nextMousePoint: { x: number; y: number }
      nextDragMoved: false
      nextMouseDownOnModel: false
    } {
  if (context.button !== 0) {
    return { shouldIgnore: true }
  }

  return {
    shouldIgnore: false,
    nextMousePoint: { x: context.clientX, y: context.clientY },
    nextDragMoved: false,
    nextMouseDownOnModel: false,
  }
}

export function resolveContextMenu(context: ContextMenuContext): boolean {
  return context.hasPoint && context.insideInteractionArea
}

export function resolveWheel(context: WheelContext):
  | { shouldIgnore: true; shouldPreventDefault: boolean }
  | { shouldIgnore: false; shouldPreventDefault: true; nextScale: number } {
  if (context.isDraggingWindow || (context.buttons & 1) === 1) {
    return { shouldIgnore: true, shouldPreventDefault: true }
  }

  if (!context.hasPoint || !context.insideInteractionArea) {
    return { shouldIgnore: true, shouldPreventDefault: false }
  }

  const scaleFactor = context.deltaY > 0 ? 0.96 : 1.04
  const nextScale = Math.min(context.maxScale, Math.max(context.minScale, context.currentScale * scaleFactor))

  if (Math.abs(nextScale - context.currentScale) < 0.0001) {
    return { shouldIgnore: true, shouldPreventDefault: true }
  }

  return { shouldIgnore: false, shouldPreventDefault: true, nextScale }
}

export function resolveMouseLeave(context: MouseLeaveContext): boolean {
  return !context.isDraggingWindow
}

export function resolveDragEnd(isDraggingWindow: boolean, now: number): DragEndResult {
  return {
    shouldFinish: isDraggingWindow,
    nextDragCooldownUntil: now + 180,
    nextDragMoved: false,
    nextModelHovering: false,
    draggedAt: now,
  }
}
