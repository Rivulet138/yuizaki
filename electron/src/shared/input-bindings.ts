export type MouseSideButton = 4 | 5
export type KeyboardShortcutAction = 'interact' | 'lock' | 'openPanel' | 'toggleVision' | 'emergencyStop'

export interface InputBindingSettings {
  pushToTalk: {
    enabled: boolean
    mouseButton: MouseSideButton
  }
  keyboard: Record<KeyboardShortcutAction, string>
}

export interface InputBindingSettingsPatch {
  pushToTalk?: Partial<InputBindingSettings['pushToTalk']>
  keyboard?: Partial<InputBindingSettings['keyboard']>
}

export interface InputBindingRegistrationStatus {
  mouseHookAvailable: boolean
  pushToTalkActive: boolean
  keyboard: Record<KeyboardShortcutAction, boolean>
  errors: string[]
}

export interface InputBindingSnapshot {
  settings: InputBindingSettings
  status: InputBindingRegistrationStatus
}

export const DEFAULT_INPUT_BINDINGS: InputBindingSettings = {
  pushToTalk: {
    enabled: true,
    mouseButton: 5,
  },
  keyboard: {
    interact: 'Control+Shift+P',
    lock: 'Control+Shift+L',
    openPanel: 'Control+Shift+O',
    toggleVision: 'Control+Alt+V',
    emergencyStop: 'Control+Shift+Escape',
  },
}

const normalizeAccelerator = (value: unknown, fallback: string): string => {
  if (value === undefined) return fallback
  if (typeof value !== 'string') return fallback
  return value.trim().slice(0, 80)
}

export const normalizeInputBindingSettings = (value: unknown): InputBindingSettings => {
  const record = typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
  const pushToTalk = typeof record['pushToTalk'] === 'object' && record['pushToTalk'] !== null
    ? record['pushToTalk'] as Record<string, unknown>
    : {}
  const keyboard = typeof record['keyboard'] === 'object' && record['keyboard'] !== null
    ? record['keyboard'] as Record<string, unknown>
    : {}
  const mouseButton = Number(pushToTalk['mouseButton'])

  return {
    pushToTalk: {
      enabled: typeof pushToTalk['enabled'] === 'boolean'
        ? pushToTalk['enabled']
        : DEFAULT_INPUT_BINDINGS.pushToTalk.enabled,
      mouseButton: mouseButton === 4 ? 4 : DEFAULT_INPUT_BINDINGS.pushToTalk.mouseButton,
    },
    keyboard: {
      interact: normalizeAccelerator(keyboard['interact'], DEFAULT_INPUT_BINDINGS.keyboard.interact),
      lock: normalizeAccelerator(keyboard['lock'], DEFAULT_INPUT_BINDINGS.keyboard.lock),
      openPanel: normalizeAccelerator(keyboard['openPanel'], DEFAULT_INPUT_BINDINGS.keyboard.openPanel),
      toggleVision: normalizeAccelerator(keyboard['toggleVision'], DEFAULT_INPUT_BINDINGS.keyboard.toggleVision),
      emergencyStop: normalizeAccelerator(keyboard['emergencyStop'], DEFAULT_INPUT_BINDINGS.keyboard.emergencyStop),
    },
  }
}

export const mergeInputBindingSettings = (
  current: InputBindingSettings,
  patch: InputBindingSettingsPatch,
): InputBindingSettings => normalizeInputBindingSettings({
  pushToTalk: { ...current.pushToTalk, ...patch.pushToTalk },
  keyboard: { ...current.keyboard, ...patch.keyboard },
})

export const mouseButtonLabel = (button: MouseSideButton): string =>
  button === 4 ? '鼠标侧键 1' : '鼠标侧键 2'
