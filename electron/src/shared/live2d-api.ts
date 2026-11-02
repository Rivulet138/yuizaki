import type { AvatarCapabilitySnapshot, AvatarCommandResult } from './avatar-command'
import type { PetControlState, PetRendererStatePayload } from './pet-control'
import type { DesktopPetEventDispatchResult, DesktopPetEventRecord } from './plugin'

export type Live2dListener = (...args: unknown[]) => void

export interface Live2dApi {
  pet: {
    rendererReady(): void
    setPosition(x: number, y: number): void
    dragWindow(deltaX: number, deltaY: number): void
    endWindowDrag(): void
    setMouseIgnore(ignore: boolean, forward?: boolean, force?: boolean): void
    setExpression(name: string): void
    playAnimation(name: string): void
    saveScale(scale: number): void
    setLocked(locked: boolean): Promise<unknown>
    setClickThrough(clickThrough: boolean): Promise<unknown>
    completeAdjustment(): Promise<PetControlState>
    cancelAdjustment(): Promise<PetControlState>
    snapBottomRight(): Promise<unknown>
    reloadRenderer(): Promise<unknown>
    savePosition(x: number, y: number): void
    reportState(payload: PetRendererStatePayload): void
    dispatchEvent(payload: DesktopPetEventRecord): Promise<DesktopPetEventDispatchResult>
    openControlPanel(): void
    openChatCenter(): void
    reportAvatarCapabilities(payload: AvatarCapabilitySnapshot | null): void
    reportAvatarCommandResult(payload: AvatarCommandResult): void
    reportLipSyncReady(payload: { requestId: string; ready: boolean }): void
  }
  interact: {
    enable(): Promise<PetControlState>
    disable(): Promise<PetControlState>
  }
  on(channel: string, callback: Live2dListener): void
  off(channel: string, callback: Live2dListener): void
}
