import { contextBridge, ipcRenderer } from 'electron'
import type { AvatarCapabilitySnapshot, AvatarCommandResult } from '../shared/avatar-command'
import type { PetControlState, PetRendererStatePayload } from '../shared/pet-control'
import type { DesktopPetEventDispatchResult, DesktopPetEventRecord } from '../shared/plugin'

type ListenerCallback = (...args: unknown[]) => void
const callbackMap = new WeakMap<ListenerCallback, Map<string, ListenerCallback>>()

const live2dApi = {
  pet: {
    rendererReady: () => ipcRenderer.send('pet:renderer-ready'),
    setPosition: (x: number, y: number) =>
      ipcRenderer.send('pet:set-position', { x, y }),
    dragWindow: (deltaX: number, deltaY: number) =>
      ipcRenderer.send('pet:drag-window', { deltaX, deltaY }),
    endWindowDrag: () => ipcRenderer.send('pet:drag-window-end'),
    setMouseIgnore: (ignore: boolean, forward = true) =>
      ipcRenderer.send('pet:set-ignore-mouse-events', { ignore, forward }),
    setExpression: (name: string) =>
      ipcRenderer.send('pet:set-expression', { name }),
    playAnimation: (name: string) =>
      ipcRenderer.send('pet:play-animation', { name }),
    saveScale: (scale: number) =>
      ipcRenderer.send('pet:save-scale', { scale }),
    setLocked: (locked: boolean) =>
      ipcRenderer.invoke('pet:set-locked', locked),
    setClickThrough: (clickThrough: boolean) =>
      ipcRenderer.invoke('pet:set-click-through', clickThrough),
    completeAdjustment: () =>
      ipcRenderer.invoke('pet:complete-adjustment') as Promise<PetControlState>,
    cancelAdjustment: () =>
      ipcRenderer.invoke('pet:cancel-adjustment') as Promise<PetControlState>,
    snapBottomRight: () => ipcRenderer.invoke('pet:snap-bottom-right'),
    reloadRenderer: () => ipcRenderer.invoke('pet:reload-renderer'),
    savePosition: (x: number, y: number) =>
      ipcRenderer.send('pet:save-position', { x, y }),
    reportState: (payload: PetRendererStatePayload) =>
      ipcRenderer.send('pet:state-changed', payload),
    dispatchEvent: (payload: DesktopPetEventRecord) =>
      ipcRenderer.invoke('pet:dispatch-event', payload) as Promise<DesktopPetEventDispatchResult>,
    openControlPanel: () => ipcRenderer.send('pet:open-control-panel'),
    openChatCenter: () => ipcRenderer.send('pet:open-chat-center'),
    reportAvatarCapabilities: (payload: AvatarCapabilitySnapshot | null) =>
      ipcRenderer.send('pet:avatar-capabilities', payload),
    reportAvatarCommandResult: (payload: AvatarCommandResult) =>
      ipcRenderer.send('pet:avatar-command-result', payload),
    reportLipSyncReady: (payload: { requestId: string; ready: boolean }) =>
      ipcRenderer.send('pet:lipsync-ready', payload),
  },

  interact: {
    enable: () => ipcRenderer.send('pet:interact-enable'),
    disable: () => ipcRenderer.send('pet:interact-disable'),
  },

  on: (channel: string, callback: ListenerCallback) => {
    const validChannels = [
      'pet:apply-config',
      'pet:interact-toggle',
      'pet:request-state',
      'pet:trigger-expression',
      'pet:trigger-expression-mix',
      'pet:trigger-emotion',
      'pet:trigger-animation',
      'pet:behavior-state',
      'pet:companion-idle-profile',
      'pet:lipsync-start',
      'pet:lipsync-stop',
      'pet:lipsync-level',
      'pet:lipsync-viseme',
      'pet:avatar-command',
      'pet:request-avatar-capabilities',
    ]

    if (validChannels.includes(channel)) {
      const channelCallbacks = callbackMap.get(callback) ?? new Map<string, ListenerCallback>()
      if (channelCallbacks.has(channel)) {
        return
      }
      const wrapped = (_: unknown, ...args: unknown[]) => callback(...args)
      channelCallbacks.set(channel, wrapped)
      callbackMap.set(callback, channelCallbacks)
      ipcRenderer.on(channel, wrapped)
    }
  },

  off: (channel: string, callback: ListenerCallback) => {
    const channelCallbacks = callbackMap.get(callback)
    const wrapped = channelCallbacks?.get(channel)
    if (!wrapped) {
      return
    }
    ipcRenderer.removeListener(channel, wrapped)
    channelCallbacks?.delete(channel)
    if (channelCallbacks?.size === 0) {
      callbackMap.delete(callback)
    }
  },
}

contextBridge.exposeInMainWorld('live2dApi', live2dApi)

declare global {
  interface Window {
    live2dApi: typeof live2dApi
    __petTestState?: {
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
      interactionBounds: {
        x: number
        y: number
        width: number
        height: number
      } | null
    }
  }
}
