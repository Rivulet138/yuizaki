import type { PetInteractionBoundsPayload } from '../shared/pet-control'

export interface PetTestState {
  lastPointerDownAt: number | null
  lastPointerDownHit: boolean | null
  lastMouseUpAt: number | null
  lastMouseUpTriggeredClick: boolean | null
  lastHitAreaName: string | null
  lastExpressionName: string | null
  lastMotionGroup: string | null
  lastMotionIndex: number | null
  lastChatOpenAt: number | null
  lastClickTriggeredAt: number | null
  lastRightClickTriggeredAt: number | null
  lastChatCenterRequestAt: number | null
  lastDragStartAt: number | null
  lastDragEndAt: number | null
  dragMoveCount: number
  interactionBounds: PetInteractionBoundsPayload | null
}

export const DEFAULT_PET_TEST_STATE: PetTestState = {
  lastPointerDownAt: null,
  lastPointerDownHit: null,
  lastMouseUpAt: null,
  lastMouseUpTriggeredClick: null,
  lastHitAreaName: null,
  lastExpressionName: null,
  lastMotionGroup: null,
  lastMotionIndex: null,
  lastChatOpenAt: null,
  lastClickTriggeredAt: null,
  lastRightClickTriggeredAt: null,
  lastChatCenterRequestAt: null,
  lastDragStartAt: null,
  lastDragEndAt: null,
  dragMoveCount: 0,
  interactionBounds: null,
}

export function syncPetTestState(state: PetTestState): void {
  ;(window as typeof window & { __petTestState?: PetTestState }).__petTestState = {
    ...state,
  }
}
