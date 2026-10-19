/** Renderer-safe shape of the preload bridge.
 *
 * Keep this declaration independent from Electron and Node types. The preload
 * implementation remains the strongly typed source of truth; renderer code
 * only needs the callable surface exposed by contextBridge.
 */
type BridgeFunction = (...args: any[]) => any

type BridgeNamespace = Record<string, BridgeFunction>

export interface PetApi {
  onboarding?: BridgeNamespace
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
