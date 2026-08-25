import type { InputBindingRegistrationStatus, InputBindingSettings } from '../shared/input-bindings'
import type { DesktopActionBridge } from './desktop-action-bridge'

interface InputBindingRegistrar {
  register(settings: InputBindingSettings): InputBindingRegistrationStatus
}

const pendingRebinds = new WeakMap<object, Promise<void>>()

export class InputBindingRebindError extends Error {
  readonly code = 'DA_HOTKEY_REBIND_STOP_UNCONFIRMED'

  constructor() {
    super('Emergency stop could not be confirmed; existing input bindings were preserved')
    this.name = 'InputBindingRebindError'
  }
}

export const rebindInputBindingsWithDesktopActionFence = async (
  settings: InputBindingSettings,
  shortcuts: InputBindingRegistrar,
  desktopActionBridge: Pick<DesktopActionBridge, 'emergencyStop'>,
): Promise<InputBindingRegistrationStatus> => {
  const key = desktopActionBridge as object
  const execute = async () => {
    const stop = await desktopActionBridge.emergencyStop()
    if (!stop.ok) throw new InputBindingRebindError()
    return shortcuts.register(settings)
  }
  const previous = pendingRebinds.get(key)
  const operation = previous === undefined
    ? execute()
    : previous.catch(() => undefined).then(execute)
  const tail = operation.then(() => undefined, () => undefined)
  pendingRebinds.set(key, tail)
  try {
    return await operation
  } finally {
    if (pendingRebinds.get(key) === tail) pendingRebinds.delete(key)
  }
}
