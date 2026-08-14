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

export function resolvePointerDragStart(options: {
  button: number
  hitModel: boolean
  interactMode: boolean
  locked: boolean
}): { shouldStart: boolean; modelInteraction: boolean } {
  const modelInteraction = options.button === 0 && options.hitModel
  return {
    shouldStart:
      options.button === 0 &&
      !options.locked &&
      (options.hitModel || options.interactMode),
    modelInteraction,
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
