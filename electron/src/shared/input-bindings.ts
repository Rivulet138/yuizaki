export type MouseSideButton = 4 | 5
export type KeyboardShortcutAction = 'interact' | 'lock' | 'openPanel' | 'toggleVision' | 'emergencyStop'

export interface KeyboardBindingEvent {
  key: string
  code?: string
  ctrlKey?: boolean
  metaKey?: boolean
  altKey?: boolean
  shiftKey?: boolean
}

const MODIFIER_KEYS = new Set(['Control', 'Shift', 'Alt', 'Meta', 'OS', 'Command'])
const KEY_ALIASES: Record<string, string> = {
  ' ': 'Space',
  ArrowUp: 'Up',
  ArrowDown: 'Down',
  ArrowLeft: 'Left',
  ArrowRight: 'Right',
  Esc: 'Escape',
}

export const keyboardEventToKey = (event: KeyboardBindingEvent, allowUnmodified = false): string | null => {
  const key = KEY_ALIASES[event.key] ?? event.key
  if (MODIFIER_KEYS.has(key)) return null
  if (allowUnmodified && key.length > 0) return key.length === 1 ? key.toUpperCase() : key
  if (/^[a-z0-9]$/i.test(key)) return key.toUpperCase()
  if (/^F(?:[1-9]|1\d|2[0-4])$/.test(key)) return key
  if (['Space', 'Tab', 'Enter', 'Escape', 'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown', 'Insert', 'Delete'].includes(key)) {
    return key
  }
  return null
}

export const keyboardEventToAccelerator = (event: KeyboardBindingEvent, allowUnmodified = false): string | null => {
  const key = keyboardEventToKey(event, allowUnmodified)
  if (!key) return null
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Control')
  if (event.metaKey) modifiers.push('Command')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (!allowUnmodified && !modifiers.length && !key.startsWith('F')) return null
  return [...modifiers, key].join('+')
}

const normalizedAcceleratorParts = (accelerator: string): { modifiers: Set<string>; key: string } | null => {
  const parts = accelerator.split('+').map((part) => part.trim()).filter(Boolean)
  if (!parts.length) return null
  const key = parts.pop() as string
  const modifiers = new Set(parts.map((part) => part.toLowerCase()))
  return { modifiers, key: KEY_ALIASES[key] ?? key }
}

export const normalizeKeyboardAccelerator = (value: unknown): string => {
  if (typeof value !== 'string') return ''
  const parts = value.trim().split('+').map((part) => part.trim()).filter(Boolean)
  if (!parts.length) return ''
  const rawKey = parts.pop() as string
  const key = KEY_ALIASES[rawKey] ?? rawKey
  if (!key) return ''
  const modifiers = parts.map((part) => {
    const normalized = part.toLowerCase()
    if (normalized === 'ctrl' || normalized === 'control') return 'Control'
    if (normalized === 'cmd' || normalized === 'command') return 'Command'
    if (normalized === 'commandorcontrol' || normalized === 'cmdorctrl') return 'CommandOrControl'
    if (normalized === 'alt' || normalized === 'option') return 'Alt'
    if (normalized === 'shift') return 'Shift'
    return ''
  })
  if (modifiers.some((modifier) => !modifier)) return ''
  const uniqueModifiers = [...new Set(modifiers)]
  const normalizedKey = keyboardEventToKey({ key }, true)
  if (!normalizedKey) return ''
  return [...uniqueModifiers, normalizedKey].join('+')
}

export const acceleratorMatchesKeyboardEvent = (
  event: KeyboardBindingEvent,
  accelerator: string,
): boolean => {
  const parsed = normalizedAcceleratorParts(accelerator)
  if (!parsed) return false
  const eventKey = keyboardEventToKey(event, true)
  if (!eventKey || eventKey.toLowerCase() !== parsed.key.toLowerCase()) return false
  const expected = parsed.modifiers
  const wantsCommandOrControl = expected.has('commandorcontrol')
  const wantsCommand = expected.has('command') && !wantsCommandOrControl
  const wantsControl = expected.has('control') && !wantsCommandOrControl
  if (wantsCommandOrControl) {
    if (!event.ctrlKey && !event.metaKey) return false
  } else if (Boolean(event.ctrlKey) !== wantsControl || Boolean(event.metaKey) !== wantsCommand) {
    return false
  }
  if (Boolean(event.altKey) !== expected.has('alt')) return false
  if (Boolean(event.shiftKey) !== expected.has('shift')) return false
  return true
}

export const findKeyboardBindingConflicts = (
  keyboard: InputBindingSettings['keyboard'],
): Array<{ accelerator: string; actions: KeyboardShortcutAction[] }> => {
  const groups = new Map<string, KeyboardShortcutAction[]>()
  for (const action of Object.keys(keyboard) as KeyboardShortcutAction[]) {
    const accelerator = normalizeKeyboardAccelerator(keyboard[action]).toLowerCase()
    if (!accelerator) continue
    const actions = groups.get(accelerator) ?? []
    actions.push(action)
    groups.set(accelerator, actions)
  }
  return [...groups.entries()]
    .filter(([, actions]) => actions.length > 1)
    .map(([accelerator, actions]) => ({ accelerator, actions }))
}

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
    // Global mouse hooks require explicit user opt-in.
    enabled: false,
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
  return normalizeKeyboardAccelerator(value).slice(0, 80)
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
