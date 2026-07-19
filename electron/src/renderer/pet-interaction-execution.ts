export interface PassthroughContext {
  now: number
  dragCooldownUntil: number
  mousePassthrough: boolean
  lastPassthroughSwitchAt: number
  minSwitchMs: number
  immediate: boolean
  ignore: boolean
}

export interface PassthroughDecision {
  shouldSkip: boolean
  shouldApplyImmediately: boolean
  delayMs: number
}

export interface MouseCaptureContext {
  hasPoint: boolean
  isDraggingWindow: boolean
  mousePassthrough: boolean
  hoverHysteresisPx: number
  hoveringInteractionArea: boolean
}

export interface MouseCaptureDecision {
  forceCapture: boolean
  nextIgnore: boolean
  nextCursor: 'default' | 'pointer' | 'grab' | 'grabbing'
}

export interface CursorContext {
  hasCanvas: boolean
  isDraggingWindow: boolean
  hoveringModel: boolean
  modelHovering: boolean
  interactMode: boolean
  locked?: boolean
}

export function resolvePassthroughStrategy(context: PassthroughContext): PassthroughDecision {
  if (context.now < context.dragCooldownUntil) {
    return { shouldSkip: true, shouldApplyImmediately: false, delayMs: 0 }
  }

  if (context.mousePassthrough === context.ignore) {
    return { shouldSkip: true, shouldApplyImmediately: false, delayMs: 0 }
  }

  const elapsed = context.now - context.lastPassthroughSwitchAt
  if (context.immediate || elapsed >= context.minSwitchMs) {
    return { shouldSkip: false, shouldApplyImmediately: true, delayMs: 0 }
  }

  return {
    shouldSkip: false,
    shouldApplyImmediately: false,
    delayMs: context.minSwitchMs - elapsed,
  }
}

export function resolveMouseCapture(context: MouseCaptureContext): MouseCaptureDecision {
  if (context.isDraggingWindow) {
    return {
      forceCapture: true,
      nextIgnore: false,
      nextCursor: 'grabbing',
    }
  }

  if (!context.hasPoint) {
    return {
      forceCapture: false,
      nextIgnore: true,
      nextCursor: 'default',
    }
  }

  return {
    forceCapture: false,
    nextIgnore: !context.hoveringInteractionArea,
    nextCursor: context.hoveringInteractionArea ? 'pointer' : 'default',
  }
}

export function resolveCursor(context: CursorContext): 'default' | 'pointer' | 'grab' | 'grabbing' {
  if (context.locked) {
    return context.hoveringModel || context.modelHovering ? 'pointer' : 'default'
  }

  if (context.isDraggingWindow) {
    return 'grabbing'
  }

  if (!context.hoveringModel && !context.modelHovering) {
    return 'default'
  }

  return context.interactMode ? 'grab' : 'pointer'
}
