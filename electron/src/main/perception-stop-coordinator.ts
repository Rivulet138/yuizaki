import type { ComputerUseBridge } from './computer-use-bridge'
import type { AuthorizedPerceptionBridge } from './authorized-perception-bridge'
import type { DesktopActionBridge } from './desktop-action-bridge'

export const stopDesktopAutomationWithPerceptionFence = async (
  computerUseBridge: Pick<ComputerUseBridge, 'stop'>,
  desktopActionBridge: Pick<DesktopActionBridge, 'emergencyStop'>,
  perceptionBridge: Pick<AuthorizedPerceptionBridge, 'beginStopFence' | 'interrupt'>,
  source: 'ipc' | 'shortcut' | 'host',
) => {
  perceptionBridge.beginStopFence()
  const [desktopActionResult, computerUseResult] = await Promise.all([
    desktopActionBridge.emergencyStop(),
    computerUseBridge.stop(source),
  ])
  if (
    computerUseResult.ok
    && Number.isSafeInteger(computerUseResult.data.revision)
    && Number(computerUseResult.data.revision) >= 0
  ) {
    perceptionBridge.interrupt(Number(computerUseResult.data.revision))
  }
  return {
    computerUse: computerUseResult,
    desktopAction: desktopActionResult,
  }
}

export const stopComputerUseWithPerceptionFence = async (
  computerUseBridge: Pick<ComputerUseBridge, 'stop'>,
  perceptionBridge: Pick<AuthorizedPerceptionBridge, 'beginStopFence' | 'interrupt'>,
  source: 'ipc' | 'shortcut' | 'host',
) => {
  perceptionBridge.beginStopFence()
  const result = await computerUseBridge.stop(source)
  if (result.ok && Number.isSafeInteger(result.data.revision) && Number(result.data.revision) >= 0) {
    perceptionBridge.interrupt(Number(result.data.revision))
  }
  return result
}
