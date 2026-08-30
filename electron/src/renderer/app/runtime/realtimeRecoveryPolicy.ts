export type RealtimeRecoveryStatus = 'idle' | 'connecting' | 'ready' | 'recording' | 'responding' | 'interrupting' | 'error' | 'closed'

export const shouldOfferRealtimeRecovery = (options: {
  responseMode: string
  recording: boolean
  ttsPlaying: boolean
  status: RealtimeRecoveryStatus
}): boolean => options.responseMode === 'instant'
  && !options.recording
  && !options.ttsPlaying
  && (options.status === 'error' || options.status === 'closed')

/** A user can stop an active realtime response before its first audio packet. */
export const shouldOfferRealtimeInterrupt = (options: {
  ttsPlaying: boolean
  status: RealtimeRecoveryStatus
}): boolean => options.ttsPlaying
  || options.status === 'responding'
  || options.status === 'interrupting'
