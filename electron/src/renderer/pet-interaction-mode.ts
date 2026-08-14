export type PetInteractionModeState = 'locked' | 'dragging' | 'adjusting' | 'interactive' | 'passthrough'

export interface PetInteractionModeContext {
  locked: boolean
  isDraggingWindow: boolean
  hoveringInteractionArea: boolean
  interactMode: boolean
}

export interface PetInteractionModeDecision {
  state: PetInteractionModeState
  shouldIgnoreMouse: boolean
  cursor: 'default' | 'pointer' | 'grab' | 'grabbing'
}

export const resolveInteractionMode = (
  context: PetInteractionModeContext,
): PetInteractionModeDecision => {
  if (context.locked) {
    return {
      state: 'locked',
      shouldIgnoreMouse: !context.hoveringInteractionArea,
      cursor: context.hoveringInteractionArea ? 'pointer' : 'default',
    }
  }

  if (context.isDraggingWindow) {
    return {
      state: 'dragging',
      shouldIgnoreMouse: false,
      cursor: 'grabbing',
    }
  }

  if (context.interactMode) {
    return {
      state: 'adjusting',
      shouldIgnoreMouse: false,
      cursor: context.hoveringInteractionArea ? 'grab' : 'default',
    }
  }

  if (context.hoveringInteractionArea) {
    return {
      state: 'interactive',
      shouldIgnoreMouse: false,
      cursor: context.interactMode ? 'grab' : 'pointer',
    }
  }

  return {
    state: 'passthrough',
    shouldIgnoreMouse: true,
    cursor: 'default',
  }
}
