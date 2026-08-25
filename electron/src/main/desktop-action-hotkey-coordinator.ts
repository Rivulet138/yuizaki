import type { InputBindingRegistrationStatus } from '../shared/input-bindings'
import type { DesktopActionBridge } from './desktop-action-bridge'

export const fenceDesktopActionsWhenHotkeyUnavailable = (
  status: InputBindingRegistrationStatus,
  desktopActionBridge: Pick<DesktopActionBridge, 'emergencyStop'>,
): boolean => {
  if (status.keyboard.emergencyStop) return false
  void desktopActionBridge.emergencyStop()
  return true
}
