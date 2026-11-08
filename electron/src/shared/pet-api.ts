/** Renderer-safe shape of the preload bridge.
 *
 * Keep this declaration independent from Electron and Node types. The preload
 * implementation remains the strongly typed source of truth; renderer code
 * only needs the callable surface exposed by contextBridge.
 */
import type { DesktopActionResult, DesktopActionStatus } from './desktop-action'
import type {
  OnboardingCancelRunRequest,
  OnboardingDeviceProbeReport,
  OnboardingProbeRequest,
  OnboardingReadinessSnapshot,
  OnboardingRepairRequest,
  OnboardingRetryRequest,
} from './onboarding-readiness'

type BridgeFunction = (...args: any[]) => any

type BridgeNamespace = Record<string, BridgeFunction>

export interface PetApi {
  desktopAction?: {
    status(): Promise<DesktopActionResult<DesktopActionStatus>>
    enable(): Promise<DesktopActionResult<DesktopActionStatus>>
    disable(): Promise<DesktopActionResult<DesktopActionStatus>>
    rearm(): Promise<DesktopActionResult<DesktopActionStatus>>
    manageAuthorization(): Promise<DesktopActionResult<DesktopActionStatus>>
  }
  onboarding?: {
    snapshot(): Promise<OnboardingReadinessSnapshot>
    startBackend(): Promise<OnboardingReadinessSnapshot>
    cancelBackend(): Promise<OnboardingReadinessSnapshot>
    cancelRun(request: OnboardingCancelRunRequest): Promise<OnboardingReadinessSnapshot>
    reportDeviceProbe(report: OnboardingDeviceProbeReport): Promise<OnboardingReadinessSnapshot>
    runProbe(request?: OnboardingProbeRequest): Promise<OnboardingReadinessSnapshot>
    retry(request: OnboardingRetryRequest): Promise<OnboardingReadinessSnapshot>
    runRepair(request: OnboardingRepairRequest): Promise<OnboardingReadinessSnapshot>
  }
  pet?: BridgeNamespace
  live2d?: BridgeNamespace
  screen?: BridgeNamespace
  shell?: BridgeNamespace
  python?: BridgeNamespace
  runtime?: BridgeNamespace
  inputBindings?: BridgeNamespace
  window?: BridgeNamespace
  on?: BridgeFunction
  off?: BridgeFunction
}
