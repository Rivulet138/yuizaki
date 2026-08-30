import manifestJson from './runtime-protocol-manifest.json'

type ProtocolManifest = typeof manifestJson

export const runtimeProtocolManifest: ProtocolManifest = manifestJson
export const SocketEvents = runtimeProtocolManifest.production_protocol.socket_events
export type SocketEventName = typeof SocketEvents[keyof typeof SocketEvents]
