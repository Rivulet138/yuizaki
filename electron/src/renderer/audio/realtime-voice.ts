import { API_ORIGIN, requestJson } from '@/api/clients/http-client'

export type RealtimeVoiceStatus =
  | 'idle'
  | 'connecting'
  | 'ready'
  | 'recording'
  | 'responding'
  | 'error'
  | 'closed'

export interface RealtimeVoiceTurn {
  turnId: string
  userText: string
  assistantText: string
  model: string
  workspaceId: string
  sessionId: string
}

export interface RealtimeVoiceEventMap {
  status: { status: RealtimeVoiceStatus }
  'input-partial': { text: string }
  'assistant-delta': { text: string; delta: string }
  'turn-complete': RealtimeVoiceTurn
  connect: { elapsedMs: number }
  'speech-end': { elapsedMs: number }
  'response-start': { elapsedMs: number }
  'playback-start': { elapsedMs: number }
  'playback-end': Record<string, never>
  'lip-sync-level': { level: number; active: boolean }
  'interrupt-ack': { elapsedMs: number }
  error: { message: string; fatal: boolean }
}

interface ClientSecretResponse {
  client_secret: string
  expires_at?: number | null
  model: string
  voice: string
  workspace_id: string
  session_id: string
}

type RealtimeServerEvent = {
  type?: unknown
  delta?: unknown
  transcript?: unknown
  response?: unknown
  error?: unknown
}

type RealtimeVoiceListener<K extends keyof RealtimeVoiceEventMap> =
  (payload: RealtimeVoiceEventMap[K]) => void

const REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls'
const MIN_PUSH_TO_TALK_MS = 120
const TRANSCRIPT_GRACE_MS = 1_200
const ICE_GATHER_TIMEOUT_MS = 2_000
const DISCONNECT_GRACE_MS = 5_000
const MAX_REUSABLE_SESSION_MS = 55 * 60 * 1_000
const OUTPUT_ANALYSIS_INTERVAL_MS = 33
const OUTPUT_ANALYSIS_KEEPALIVE_MS = 120

const createTurnId = () => `rt_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`

const readString = (value: unknown): string => typeof value === 'string' ? value : ''

const responseErrorMessage = async (response: Response): Promise<string> => {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const payload = await response.json().catch(() => null) as { error?: { message?: unknown } } | null
    const message = readString(payload?.error?.message)
    if (message) return message
  }
  return (await response.text().catch(() => '')).trim() || `Realtime call failed with HTTP ${response.status}`
}

const waitForIceGathering = (peer: RTCPeerConnection): Promise<void> => {
  if (peer.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timeoutId)
      peer.removeEventListener('icegatheringstatechange', onStateChange)
      resolve()
    }
    const onStateChange = () => {
      if (peer.iceGatheringState === 'complete') finish()
    }
    const timeoutId = window.setTimeout(finish, ICE_GATHER_TIMEOUT_MS)
    peer.addEventListener('icegatheringstatechange', onStateChange)
  })
}

export class RealtimeVoiceSession {
  private status: RealtimeVoiceStatus = 'idle'
  private peer: RTCPeerConnection | null = null
  private dataChannel: RTCDataChannel | null = null
  private mediaStream: MediaStream | null = null
  private audioElement: HTMLAudioElement | null = null
  private outputAudioContext: AudioContext | null = null
  private outputAudioSource: MediaStreamAudioSourceNode | null = null
  private outputAnalyser: AnalyserNode | null = null
  private outputSamples: Float32Array | null = null
  private outputAnalysisFrame: number | null = null
  private outputLipSyncActive = false
  private outputLevelReportedAt = 0
  private outputLevelReported = 0
  private connectionPromise: Promise<void> | null = null
  private listeners = new Map<keyof RealtimeVoiceEventMap, Set<(payload: never) => void>>()
  private pressStartedAt: number | null = null
  private speechEndedAt: number | null = null
  private interruptStartedAt: number | null = null
  private responseActive = false
  private playbackReported = false
  private inputTranscript = ''
  private assistantTranscript = ''
  private assistantDeltaText = ''
  private responseDone = false
  private finalizeTimer: number | null = null
  private model = ''
  private workspaceId = ''
  private sessionId = ''
  private connectedAt = 0
  private disconnectTimer: number | null = null

  on<K extends keyof RealtimeVoiceEventMap>(
    event: K,
    listener: RealtimeVoiceListener<K>,
  ): () => void {
    const listeners = this.listeners.get(event) ?? new Set()
    listeners.add(listener as (payload: never) => void)
    this.listeners.set(event, listeners)
    return () => listeners.delete(listener as (payload: never) => void)
  }

  getStatus(): RealtimeVoiceStatus {
    return this.status
  }

  isConnected(): boolean {
    return this.dataChannel?.readyState === 'open'
      && this.peer?.connectionState !== 'failed'
      && this.peer?.connectionState !== 'closed'
      && Date.now() - this.connectedAt < MAX_REUSABLE_SESSION_MS
  }

  isConnectedFor(options: { workspaceId: string; sessionId: string }): boolean {
    return this.isConnected()
      && this.workspaceId === options.workspaceId
      && this.sessionId === options.sessionId
  }

  async connect(options: { workspaceId: string; sessionId: string }): Promise<void> {
    if (
      this.isConnectedFor(options)
    ) return
    if (this.connectionPromise) return this.connectionPromise

    this.connectionPromise = this.openConnection(options)
      .catch((error) => {
        this.setStatus('error')
        this.emit('error', {
          message: error instanceof Error ? error.message : 'Realtime voice connection failed',
          fatal: true,
        })
        this.disposeConnection()
        throw error
      })
      .finally(() => {
        this.connectionPromise = null
      })
    return this.connectionPromise
  }

  async startPushToTalk(options: { workspaceId: string; sessionId: string }): Promise<void> {
    await this.connect(options)
    void this.outputAudioContext?.resume().catch(() => undefined)
    if (this.responseActive) {
      this.interrupt()
      throw new Error('Previous realtime response is being interrupted')
    }
    if (this.finalizeTimer !== null) {
      throw new Error('Previous realtime transcript is still finalizing')
    }
    this.resetTurn()
    this.sendEvent({ type: 'input_audio_buffer.clear' })
    const track = this.mediaStream?.getAudioTracks()[0]
    if (!track) throw new Error('Realtime microphone track is unavailable')
    track.enabled = true
    this.pressStartedAt = performance.now()
    this.setStatus('recording')
  }

  stopPushToTalk(): boolean {
    if (this.pressStartedAt === null) return false
    const track = this.mediaStream?.getAudioTracks()[0]
    if (track) track.enabled = false
    const elapsedMs = Math.max(0, performance.now() - this.pressStartedAt)
    this.pressStartedAt = null
    this.speechEndedAt = performance.now()
    this.emit('speech-end', { elapsedMs })
    if (elapsedMs < MIN_PUSH_TO_TALK_MS) {
      this.sendEvent({ type: 'input_audio_buffer.clear' })
      this.setStatus('ready')
      return false
    }
    this.sendEvent({ type: 'input_audio_buffer.commit' })
    this.sendEvent({
      type: 'response.create',
      response: {
        output_modalities: ['audio'],
        metadata: { source: 'yuizaki_push_to_talk' },
      },
    })
    this.responseActive = true
    this.setStatus('responding')
    return true
  }

  interrupt(): void {
    if (!this.isConnected()) return
    this.interruptStartedAt = performance.now()
    this.sendEvent({ type: 'response.cancel' })
    this.sendEvent({ type: 'output_audio_buffer.clear' })
    this.responseActive = false
    this.audioElement?.pause()
    this.stopOutputLipSync()
    this.setStatus('ready')
  }

  close(): void {
    this.disposeConnection()
    this.setStatus('closed')
  }

  private async openConnection(options: { workspaceId: string; sessionId: string }): Promise<void> {
    const connectStartedAt = performance.now()
    this.disposeConnection()
    this.setStatus('connecting')
    this.workspaceId = options.workspaceId
    this.sessionId = options.sessionId

    const secret = await requestJson<ClientSecretResponse>(`${API_ORIGIN}/api/realtime/client-secret`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: options.workspaceId,
        session_id: options.sessionId,
      }),
    })
    if (!secret.client_secret.startsWith('ek_')) {
      throw new Error('Backend returned an invalid Realtime client secret')
    }
    this.model = secret.model

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    const track = stream.getAudioTracks()[0]
    if (!track) {
      stream.getTracks().forEach((item) => item.stop())
      throw new Error('No microphone audio track is available')
    }
    track.enabled = false

    const peer = new RTCPeerConnection()
    const audioElement = document.createElement('audio')
    audioElement.autoplay = true
    audioElement.setAttribute('aria-hidden', 'true')
    audioElement.style.display = 'none'
    document.body.appendChild(audioElement)
    peer.ontrack = (event) => {
      const remoteStream = event.streams[0] ?? new MediaStream([event.track])
      audioElement.srcObject = remoteStream
      this.attachOutputAnalysis(remoteStream)
      void audioElement.play().catch(() => undefined)
    }
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === 'connected') {
        this.clearDisconnectTimer()
        return
      }
      if (peer.connectionState === 'failed' || peer.connectionState === 'closed') {
        this.failConnection(peer)
        return
      }
      if (peer.connectionState === 'disconnected' && this.disconnectTimer === null) {
        this.disconnectTimer = window.setTimeout(() => {
          this.disconnectTimer = null
          if (peer.connectionState === 'disconnected') this.failConnection(peer)
        }, DISCONNECT_GRACE_MS)
      }
    }
    peer.addTrack(track, stream)

    const dataChannel = peer.createDataChannel('oai-events')
    const channelReady = new Promise<void>((resolve, reject) => {
      const timeoutId = window.setTimeout(
        () => reject(new Error('Realtime data channel timed out')),
        10_000,
      )
      dataChannel.addEventListener('open', () => {
        clearTimeout(timeoutId)
        resolve()
      }, { once: true })
      dataChannel.addEventListener('error', () => {
        clearTimeout(timeoutId)
        reject(new Error('Realtime data channel failed'))
      }, { once: true })
    })
    dataChannel.addEventListener('message', (event) => this.handleServerEvent(event.data))

    this.peer = peer
    this.dataChannel = dataChannel
    this.mediaStream = stream
    this.audioElement = audioElement

    const offer = await peer.createOffer()
    await peer.setLocalDescription(offer)
    await waitForIceGathering(peer)
    const sdp = peer.localDescription?.sdp
    if (!sdp) throw new Error('Realtime WebRTC offer did not contain SDP')

    const answer = await fetch(REALTIME_CALLS_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secret.client_secret}`,
        'Content-Type': 'application/sdp',
      },
      body: sdp,
    })
    if (!answer.ok) throw new Error(await responseErrorMessage(answer))
    await peer.setRemoteDescription({ type: 'answer', sdp: await answer.text() })
    await channelReady
    this.connectedAt = Date.now()
    this.setStatus('ready')
    this.emit('connect', { elapsedMs: Math.max(0, performance.now() - connectStartedAt) })
  }

  private handleServerEvent(raw: unknown): void {
    let event: RealtimeServerEvent
    try {
      event = typeof raw === 'string'
        ? JSON.parse(raw) as RealtimeServerEvent
        : raw as RealtimeServerEvent
    } catch {
      return
    }
    const type = readString(event.type)
    if (!type) return

    if (type === 'conversation.item.input_audio_transcription.delta') {
      const delta = readString(event.delta)
      if (delta) {
        this.inputTranscript += delta
        this.emit('input-partial', { text: this.inputTranscript })
      }
      return
    }
    if (type === 'conversation.item.input_audio_transcription.completed') {
      this.inputTranscript = readString(event.transcript).trim() || this.inputTranscript.trim()
      this.emit('input-partial', { text: this.inputTranscript })
      this.maybeFinalizeTurn()
      return
    }
    if (type === 'response.created') {
      this.responseActive = true
      const elapsedMs = this.elapsedSinceSpeechEnd()
      if (elapsedMs !== null) this.emit('response-start', { elapsedMs })
      return
    }
    if (type === 'response.output_audio_transcript.delta') {
      const delta = readString(event.delta)
      if (!delta) return
      this.assistantDeltaText += delta
      this.emit('assistant-delta', { text: this.assistantDeltaText, delta })
      return
    }
    if (type === 'response.output_audio_transcript.done') {
      this.assistantTranscript = readString(event.transcript).trim() || this.assistantDeltaText.trim()
      this.maybeFinalizeTurn()
      return
    }
    if (type === 'response.output_audio.delta' && !this.playbackReported) {
      this.startOutputLipSync()
      this.reportPlaybackStart()
      return
    }
    if (type === 'output_audio_buffer.started') {
      this.startOutputLipSync()
      this.reportPlaybackStart()
      return
    }
    if (type === 'output_audio_buffer.stopped') {
      this.stopOutputLipSync()
      return
    }
    if (type === 'response.done') {
      this.responseActive = false
      this.responseDone = true
      this.setStatus('ready')
      this.scheduleFinalizeTurn()
      return
    }
    if (type === 'output_audio_buffer.cleared' && this.interruptStartedAt !== null) {
      this.stopOutputLipSync()
      const elapsedMs = Math.max(0, performance.now() - this.interruptStartedAt)
      this.interruptStartedAt = null
      this.emit('interrupt-ack', { elapsedMs })
      return
    }
    if (type === 'error') {
      const errorRecord = event.error && typeof event.error === 'object'
        ? event.error as { message?: unknown; code?: unknown }
        : {}
      const code = readString(errorRecord.code)
      if (code === 'input_audio_buffer_commit_empty') return
      this.emit('error', {
        message: readString(errorRecord.message) || 'Realtime voice returned an error',
        fatal: false,
      })
    }
  }

  private elapsedSinceSpeechEnd(): number | null {
    return this.speechEndedAt === null
      ? null
      : Math.max(0, performance.now() - this.speechEndedAt)
  }

  private reportPlaybackStart(): void {
    if (this.playbackReported) return
    this.playbackReported = true
    const elapsedMs = this.elapsedSinceSpeechEnd()
    if (elapsedMs !== null) this.emit('playback-start', { elapsedMs })
  }

  private attachOutputAnalysis(stream: MediaStream): void {
    this.disposeOutputAnalysis()
    if (typeof window.AudioContext !== 'function') return
    try {
      const context = new AudioContext()
      const source = context.createMediaStreamSource(stream)
      const analyser = context.createAnalyser()
      analyser.fftSize = 512
      source.connect(analyser)
      this.outputAudioContext = context
      this.outputAudioSource = source
      this.outputAnalyser = analyser
      this.outputSamples = new Float32Array(analyser.fftSize)
    } catch (error) {
      console.debug('[RealtimeVoice] output audio analysis unavailable:', error)
      this.disposeOutputAnalysis()
    }
  }

  private startOutputLipSync(): void {
    void this.audioElement?.play().catch(() => undefined)
    void this.outputAudioContext?.resume().catch(() => undefined)
    if (this.outputLipSyncActive) return
    this.outputLipSyncActive = true
    this.outputLevelReported = 0
    this.outputLevelReportedAt = performance.now()
    this.emit('lip-sync-level', { level: 0, active: true })
    this.scheduleOutputAnalysis()
  }

  private stopOutputLipSync(): void {
    if (this.outputAnalysisFrame !== null) {
      window.cancelAnimationFrame(this.outputAnalysisFrame)
      this.outputAnalysisFrame = null
    }
    if (!this.outputLipSyncActive) return
    this.outputLipSyncActive = false
    this.outputLevelReported = 0
    this.emit('lip-sync-level', { level: 0, active: false })
    this.emit('playback-end', {})
  }

  private scheduleOutputAnalysis(): void {
    if (!this.outputLipSyncActive || this.outputAnalysisFrame !== null) return
    this.outputAnalysisFrame = window.requestAnimationFrame(() => {
      this.outputAnalysisFrame = null
      this.sampleOutputLevel()
      this.scheduleOutputAnalysis()
    })
  }

  private sampleOutputLevel(): void {
    if (!this.outputLipSyncActive) return
    const analyser = this.outputAnalyser
    const samples = this.outputSamples
    let level = 0
    if (analyser && samples) {
      analyser.getFloatTimeDomainData(samples)
      let sumSquares = 0
      for (const sample of samples) {
        sumSquares += sample * sample
      }
      level = Math.max(0, Math.min(1, Math.sqrt(sumSquares / samples.length)))
    }

    const now = performance.now()
    const elapsed = now - this.outputLevelReportedAt
    if (
      elapsed >= OUTPUT_ANALYSIS_INTERVAL_MS
      && (
        Math.abs(level - this.outputLevelReported) >= 0.003
        || elapsed >= OUTPUT_ANALYSIS_KEEPALIVE_MS
      )
    ) {
      this.outputLevelReported = level
      this.outputLevelReportedAt = now
      this.emit('lip-sync-level', { level, active: true })
    }
  }

  private disposeOutputAnalysis(): void {
    this.stopOutputLipSync()
    this.outputAudioSource?.disconnect()
    this.outputAudioSource = null
    this.outputAnalyser = null
    this.outputSamples = null
    if (this.outputAudioContext) {
      void this.outputAudioContext.close().catch(() => undefined)
      this.outputAudioContext = null
    }
  }

  private scheduleFinalizeTurn(): void {
    if (this.finalizeTimer !== null) window.clearTimeout(this.finalizeTimer)
    this.finalizeTimer = window.setTimeout(() => {
      this.finalizeTimer = null
      this.finalizeTurn()
    }, TRANSCRIPT_GRACE_MS)
    this.maybeFinalizeTurn()
  }

  private maybeFinalizeTurn(): void {
    if (!this.responseDone || !this.inputTranscript.trim() || !this.assistantTranscript.trim()) return
    this.finalizeTurn()
  }

  private finalizeTurn(): void {
    const userText = this.inputTranscript.trim()
    const assistantText = (this.assistantTranscript || this.assistantDeltaText).trim()
    if (!userText || !assistantText) return
    if (this.finalizeTimer !== null) {
      window.clearTimeout(this.finalizeTimer)
      this.finalizeTimer = null
    }
    this.emit('turn-complete', {
      turnId: createTurnId(),
      userText,
      assistantText,
      model: this.model,
      workspaceId: this.workspaceId,
      sessionId: this.sessionId,
    })
    this.resetTurn()
  }

  private resetTurn(): void {
    if (this.finalizeTimer !== null) {
      window.clearTimeout(this.finalizeTimer)
      this.finalizeTimer = null
    }
    this.inputTranscript = ''
    this.assistantTranscript = ''
    this.assistantDeltaText = ''
    this.responseDone = false
    this.playbackReported = false
    this.speechEndedAt = null
  }

  private sendEvent(payload: Record<string, unknown>): void {
    if (this.dataChannel?.readyState !== 'open') {
      throw new Error('Realtime data channel is not ready')
    }
    this.dataChannel.send(JSON.stringify(payload))
  }

  private setStatus(status: RealtimeVoiceStatus): void {
    if (this.status === status) return
    this.status = status
    this.emit('status', { status })
  }

  private clearDisconnectTimer(): void {
    if (this.disconnectTimer === null) return
    window.clearTimeout(this.disconnectTimer)
    this.disconnectTimer = null
  }

  private failConnection(peer: RTCPeerConnection): void {
    if (this.peer !== peer) return
    this.clearDisconnectTimer()
    this.emit('error', { message: 'Realtime voice connection was lost', fatal: true })
    this.disposeConnection()
    this.setStatus('error')
  }

  private emit<K extends keyof RealtimeVoiceEventMap>(
    event: K,
    payload: RealtimeVoiceEventMap[K],
  ): void {
    for (const listener of this.listeners.get(event) ?? []) {
      listener(payload as never)
    }
  }

  private disposeConnection(): void {
    this.clearDisconnectTimer()
    if (this.finalizeTimer !== null) {
      window.clearTimeout(this.finalizeTimer)
      this.finalizeTimer = null
    }
    if (this.dataChannel) {
      this.dataChannel.close()
      this.dataChannel = null
    }
    if (this.peer) {
      this.peer.ontrack = null
      this.peer.onconnectionstatechange = null
      this.peer.close()
      this.peer = null
    }
    this.mediaStream?.getTracks().forEach((track) => track.stop())
    this.mediaStream = null
    this.disposeOutputAnalysis()
    if (this.audioElement) {
      this.audioElement.pause()
      this.audioElement.srcObject = null
      this.audioElement.remove()
      this.audioElement = null
    }
    this.pressStartedAt = null
    this.connectedAt = 0
    this.responseActive = false
    this.resetTurn()
  }
}

export const realtimeVoiceSession = new RealtimeVoiceSession()
