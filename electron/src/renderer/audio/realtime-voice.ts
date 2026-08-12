import { API_ORIGIN, requestJson } from '@/api/clients/http-client'
import type { CompanionEventEnvelope, CompanionJobStatus } from '@/../shared/companion-event'
import type { PetControlContextPayload } from '@/../shared/types'

export type RealtimeVoiceStatus =
  | 'idle'
  | 'connecting'
  | 'ready'
  | 'recording'
  | 'responding'
  | 'error'
  | 'closed'

export interface RealtimeVoiceScope {
  workspaceId: string
  sessionId: string
  interruptionEpoch: number
  /** Stable identity for the current conversational round. */
  turnId?: string
  generationId?: string
  requestId?: string
  sequence?: number
  envelopeVersion?: 1
}

export interface RealtimeVoiceTurn extends RealtimeVoiceScope {
  turnId: string
  userText: string
  assistantText: string
  model: string
  elapsedMs: number
  actionEnvelope?: unknown
}

export interface RealtimeVoiceSessionOptions {
  workspaceId: string
  sessionId: string
  interruptionEpoch?: number
  petControlContext?: PetControlContextPayload | null
  mcpEnabled?: boolean
  webSearchEnabled?: boolean
}

export interface RealtimeVoiceEventMap {
  status: { status: RealtimeVoiceStatus }
  'input-partial': RealtimeVoiceScope & { text: string }
  'assistant-delta': RealtimeVoiceScope & { text: string; delta: string }
  'turn-complete': RealtimeVoiceTurn
  connect: { elapsedMs: number }
  'speech-end': { elapsedMs: number }
  'transcript-stable': { elapsedMs: number }
  'response-start': { elapsedMs: number }
  'playback-start': { elapsedMs: number }
  'playback-end': Record<string, never>
  'lip-sync-level': { level: number; active: boolean }
  'interrupt-ack': { elapsedMs: number }
  'agent-result': RealtimeVoiceScope & { callId: string; turnId: string; reply: string; petControl?: unknown; actionEnvelope?: unknown }
  'companion-event': CompanionEventEnvelope
  error: { message: string; fatal: boolean }
}

interface ClientSecretResponse {
  client_secret: string
  expires_at?: number | null
  model: string
  voice: string
  agent_model?: string
  workspace_id: string
  session_id: string
}

type RealtimeServerEvent = {
  type?: unknown
  delta?: unknown
  transcript?: unknown
  response?: unknown
  response_id?: unknown
  item_id?: unknown
  error?: unknown
}

interface RealtimeAgentResponse {
  choices?: Array<{ message?: { content?: unknown } }>
  pet_control?: unknown
  action_envelope?: unknown
}

type RealtimeAgentIntent = 'tool' | 'memory' | 'vision' | 'task' | 'deep_answer'

interface RealtimeAgentToolArguments {
  request: string
  intent: RealtimeAgentIntent
}

interface PendingRealtimeAgentJob {
  controller: AbortController
  turnId: string
  jobId: string
  requestId: string
  workspaceId: string
  sessionId: string
  interruptionEpoch: number
  revision: number
}

interface PendingInputCommit {
  generationId: string
  turnId: string
  requestId: string
  interruptionEpoch: number
}

type RealtimeVoiceListener<K extends keyof RealtimeVoiceEventMap> =
  (payload: RealtimeVoiceEventMap[K]) => void

const REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls'
const MIN_PUSH_TO_TALK_MS = 120
// Keep a short tail for provider transcript ordering without adding a full
// second of dead air after audio has already finished.
const TRANSCRIPT_GRACE_MS = 600
const ICE_GATHER_TIMEOUT_MS = 2_000
const DISCONNECT_GRACE_MS = 5_000
const MAX_REUSABLE_SESSION_MS = 55 * 60 * 1_000
const OUTPUT_ANALYSIS_INTERVAL_MS = 33
const OUTPUT_ANALYSIS_KEEPALIVE_MS = 120
const REALTIME_AGENT_TOOL_NAME = 'delegate_to_agent'
const REALTIME_AGENT_TIMEOUT_MS = 120_000
const MAX_COMPLETED_TOOL_CALL_IDS = 128
const MAX_RETIRED_SERVER_IDS = 64
const REALTIME_AGENT_INTENTS = new Set<RealtimeAgentIntent>([
  'tool',
  'memory',
  'vision',
  'task',
  'deep_answer',
])

const createTurnId = () => `rt_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`

const readString = (value: unknown): string => typeof value === 'string' ? value : ''

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const parseAgentToolArguments = (value: unknown, fallbackRequest: string): RealtimeAgentToolArguments => {
  const parsed = typeof value === 'string' ? JSON.parse(value) as unknown : value
  if (!isRecord(parsed)) throw new Error('Agent delegation arguments must be an object')
  const request = readString(parsed.request).trim() || fallbackRequest.trim()
  const intent = readString(parsed.intent) as RealtimeAgentIntent
  if (!request || request.length > 12_000) throw new Error('Agent delegation request is invalid')
  if (!REALTIME_AGENT_INTENTS.has(intent)) throw new Error('Agent delegation intent is invalid')
  return { request, intent }
}

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
  private inputTranscriptStableReported = false
  private assistantTranscript = ''
  private assistantDeltaText = ''
  private responseDone = false
  private finalizeTimer: number | null = null
  private model = ''
  private workspaceId = ''
  private sessionId = ''
  private connectedAt = 0
  private disconnectTimer: number | null = null
  private agentModel = ''
  private operationEpoch = 0
  private currentTurnId = createTurnId()
  private currentGenerationId = createTurnId()
  private currentRequestId = ''
  private eventSequence = 0
  private currentInterruptionEpoch = 0
  private currentTurnCancelled = false
  private currentResponseId = ''
  private currentInputItemId = ''
  private retiredResponseIds = new Set<string>()
  private retiredInputItemIds = new Set<string>()
  private pendingInputCommits: PendingInputCommit[] = []
  private petControlContext: PetControlContextPayload | null = null
  private completedToolCallIds = new Set<string>()
  private pendingAgentJobs = new Map<string, PendingRealtimeAgentJob>()
  private delegatedActionEnvelope: unknown
  private agentMcpEnabled = true
  private agentWebSearchEnabled = false

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

  getCurrentTurnIdentity(): Pick<RealtimeVoiceScope, 'turnId' | 'generationId' | 'requestId' | 'interruptionEpoch'> {
    return {
      turnId: this.currentTurnId,
      generationId: this.currentGenerationId,
      requestId: this.currentRequestId,
      interruptionEpoch: this.currentInterruptionEpoch,
    }
  }

  async connect(options: RealtimeVoiceSessionOptions): Promise<void> {
    this.agentMcpEnabled = options.mcpEnabled !== false
    this.agentWebSearchEnabled = options.webSearchEnabled === true
    this.petControlContext = options.petControlContext ?? null
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

  async startPushToTalk(options: RealtimeVoiceSessionOptions): Promise<void> {
    await this.connect(options)
    void this.outputAudioContext?.resume().catch(() => undefined)
    if (this.responseActive) {
      this.interrupt()
      throw new Error('Previous realtime response is being interrupted')
    }
    if (this.finalizeTimer !== null) {
      throw new Error('Previous realtime transcript is still finalizing')
    }
    this.currentInterruptionEpoch = options.interruptionEpoch ?? 0
    this.petControlContext = options.petControlContext ?? this.petControlContext
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
    this.pendingInputCommits.push({
      generationId: this.currentGenerationId,
      turnId: this.currentTurnId,
      requestId: this.currentRequestId,
      interruptionEpoch: this.currentInterruptionEpoch,
    })
    this.sendEvent({ type: 'input_audio_buffer.commit' })
    this.sendEvent({
      type: 'response.create',
      response: {
        output_modalities: ['audio'],
        metadata: {
          source: 'yuizaki_push_to_talk',
          envelope_version: 1,
          generation_id: this.currentGenerationId,
          turn_id: this.currentTurnId,
          request_id: this.currentRequestId,
          interruption_epoch: this.currentInterruptionEpoch,
        },
      },
    })
    this.responseActive = true
    this.setStatus('responding')
    return true
  }

  interrupt(): void {
    if (!this.isConnected()) return
    this.operationEpoch += 1
    this.currentTurnCancelled = true
    this.abortPendingToolCalls()
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
    this.agentModel = readString(secret.agent_model).trim()

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

    if (type === 'input_audio_buffer.committed') {
      const itemId = readString(event.item_id).trim()
      const pending = this.pendingInputCommits.shift()
      if (!itemId || this.retiredInputItemIds.has(itemId)) return
      const belongsToCurrentTurn = pending
        && pending.generationId === this.currentGenerationId
        && pending.turnId === this.currentTurnId
        && pending.requestId === this.currentRequestId
        && pending.interruptionEpoch === this.currentInterruptionEpoch
      if (!belongsToCurrentTurn) {
        this.rememberRetiredId(this.retiredInputItemIds, itemId)
        return
      }
      this.currentInputItemId = itemId
      return
    }

    if (type === 'conversation.item.input_audio_transcription.delta') {
      if (this.currentTurnCancelled || !this.matchesCurrentInputItem(event)) return
      const delta = readString(event.delta)
      if (delta) {
        this.inputTranscript += delta
        this.emit('input-partial', { ...this.currentScope(), text: this.inputTranscript })
      }
      return
    }
    if (type === 'conversation.item.input_audio_transcription.completed') {
      if (this.currentTurnCancelled || !this.matchesCurrentInputItem(event)) return
      this.inputTranscript = readString(event.transcript).trim() || this.inputTranscript.trim()
      this.emit('input-partial', { ...this.currentScope(), text: this.inputTranscript })
      if (!this.inputTranscriptStableReported && this.inputTranscript.trim()) {
        this.inputTranscriptStableReported = true
        const elapsedMs = this.elapsedSinceSpeechEnd()
        if (elapsedMs !== null) this.emit('transcript-stable', { elapsedMs })
      }
      this.maybeFinalizeTurn()
      return
    }
    if (type === 'response.created') {
      if (!this.acceptCreatedResponse(event.response)) return
      this.responseActive = true
      const elapsedMs = this.elapsedSinceSpeechEnd()
      if (elapsedMs !== null) this.emit('response-start', { elapsedMs })
      return
    }
    if (type === 'response.output_audio_transcript.delta') {
      if (this.currentTurnCancelled || !this.matchesCurrentResponse(event)) return
      const delta = readString(event.delta)
      if (!delta) return
      this.assistantDeltaText += delta
      this.emit('assistant-delta', { ...this.currentScope(), text: this.assistantDeltaText, delta })
      return
    }
    if (type === 'response.output_audio_transcript.done') {
      if (this.currentTurnCancelled || !this.matchesCurrentResponse(event)) return
      this.assistantTranscript = readString(event.transcript).trim() || this.assistantDeltaText.trim()
      this.maybeFinalizeTurn()
      return
    }
    if (type === 'response.output_audio.delta' && !this.playbackReported) {
      if (this.currentTurnCancelled || !this.matchesCurrentResponse(event)) return
      this.startOutputLipSync()
      this.reportPlaybackStart()
      return
    }
    if (type === 'output_audio_buffer.started') {
      if (this.currentTurnCancelled || !this.matchesCurrentResponse(event)) return
      this.startOutputLipSync()
      this.reportPlaybackStart()
      return
    }
    if (type === 'output_audio_buffer.stopped') {
      if (!this.matchesCurrentResponse(event)) return
      this.stopOutputLipSync()
      return
    }
    if (type === 'response.done') {
      if (!this.matchesCurrentResponse(event)) return
      if (this.handleCompletedResponse(event.response)) {
        this.responseActive = true
        this.setStatus('responding')
        return
      }
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

  private handleCompletedResponse(value: unknown): boolean {
    if (this.currentTurnCancelled) return false
    if (!isRecord(value) || value.status !== 'completed' || !Array.isArray(value.output)) return false
    let handled = false
    const calls: Array<{ callId: string; arguments: unknown }> = []
    for (const item of value.output) {
      if (
        !isRecord(item)
        || item.type !== 'function_call'
        || (item.status !== undefined && item.status !== 'completed')
      ) continue
      const callId = readString(item.call_id).trim()
      const name = readString(item.name).trim()
      if (!callId || name !== REALTIME_AGENT_TOOL_NAME) continue
      handled = true
      if (this.completedToolCallIds.has(callId)) continue
      while (this.completedToolCallIds.size >= MAX_COMPLETED_TOOL_CALL_IDS) {
        const oldestCallId = this.completedToolCallIds.values().next().value
        if (oldestCallId === undefined) break
        this.completedToolCallIds.delete(oldestCallId)
      }
      this.completedToolCallIds.add(callId)
      calls.push({ callId, arguments: item.arguments })
    }
    if (calls.length > 0) void this.delegateAgentCalls(calls)
    return handled
  }

  private async delegateAgentCalls(calls: Array<{ callId: string; arguments: unknown }>): Promise<void> {
    const epoch = this.operationEpoch
    let submitted = false
    for (const call of calls) {
      if (epoch !== this.operationEpoch || this.currentTurnCancelled) break
      submitted = await this.delegateToAgent(call.callId, call.arguments) || submitted
    }
    if (submitted && epoch === this.operationEpoch && !this.currentTurnCancelled && this.isConnected()) {
      this.requestAgentFollowupResponse()
    }
  }

  private async delegateToAgent(callId: string, rawArguments: unknown): Promise<boolean> {
    const epoch = this.operationEpoch
    const workspaceId = this.workspaceId
    const sessionId = this.sessionId
    const controller = new AbortController()
    const job: PendingRealtimeAgentJob = {
      controller,
      turnId: this.currentTurnId,
      jobId: `realtime-agent:${callId}`,
      requestId: `realtime_${callId}`,
      workspaceId,
      sessionId,
      interruptionEpoch: this.currentInterruptionEpoch,
      revision: 0,
    }
    this.pendingAgentJobs.set(callId, job)
    this.emitAgentJob(job, 'created')
    try {
      const args = parseAgentToolArguments(rawArguments, this.inputTranscript)
      if (!this.agentModel) throw new Error('The main Agent model is not configured')
      const result = await requestJson<RealtimeAgentResponse>(`${API_ORIGIN}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: REALTIME_AGENT_TIMEOUT_MS,
        signal: controller.signal,
        body: JSON.stringify({
          model: this.agentModel,
          messages: [{ role: 'user', content: args.request }],
          session_id: sessionId,
          workspace_id: workspaceId,
          request_id: job.requestId,
          stream: false,
          max_tokens: 4096,
          mcp_enabled: this.agentMcpEnabled,
          web_search_enabled: this.agentWebSearchEnabled,
          pet_control_context: this.petControlContext,
          autonomy_mode: 'companion',
        }),
      })
      if (!this.canCommitToolResult(epoch, job, controller)) return false
      const reply = readString(result.choices?.[0]?.message?.content).trim()
      if (!reply) throw new Error('The Agent returned an empty response')
      this.delegatedActionEnvelope = result.action_envelope
      this.emit('agent-result', {
        callId,
        turnId: job.turnId,
        generationId: this.currentGenerationId,
        requestId: job.requestId,
        sequence: this.nextSequence(),
        envelopeVersion: 1,
        workspaceId,
        sessionId,
        interruptionEpoch: job.interruptionEpoch,
        reply,
        ...(result.pet_control !== undefined ? { petControl: result.pet_control } : {}),
        ...(result.action_envelope !== undefined ? { actionEnvelope: result.action_envelope } : {}),
      })
      this.emitAgentJob(job, 'completed', { intent: args.intent })
      this.submitToolOutput(callId, {
        ok: true,
        intent: args.intent,
        reply,
      })
      return true
    } catch (error) {
      if (!this.canCommitToolResult(epoch, job, controller)) return false
      const message = error instanceof Error ? error.message : 'Agent delegation failed'
      this.emitAgentJob(job, 'failed', { error: message })
      this.submitToolOutput(callId, {
        ok: false,
        error: message,
      })
      return true
    } finally {
      if (this.pendingAgentJobs.get(callId)?.controller === controller) {
        this.pendingAgentJobs.delete(callId)
      }
    }
  }

  private canCommitToolResult(
    epoch: number,
    job: PendingRealtimeAgentJob,
    controller: AbortController,
  ): boolean {
    return !controller.signal.aborted
      && epoch === this.operationEpoch
      && job.workspaceId === this.workspaceId
      && job.sessionId === this.sessionId
      && job.turnId === this.currentTurnId
      && job.interruptionEpoch === this.currentInterruptionEpoch
      && !this.currentTurnCancelled
      && this.isConnected()
  }

  private submitToolOutput(callId: string, result: unknown): void {
    this.assistantTranscript = ''
    this.assistantDeltaText = ''
    this.sendEvent({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: callId,
        output: JSON.stringify(result),
      },
    })
  }

  private requestAgentFollowupResponse(): void {
    this.responseDone = false
    this.assistantTranscript = ''
    this.assistantDeltaText = ''
    this.sendEvent({
      type: 'response.create',
      response: {
        output_modalities: ['audio'],
        metadata: {
          source: 'yuizaki_agent_delegation',
          envelope_version: 1,
          generation_id: this.currentGenerationId,
          turn_id: this.currentTurnId,
          request_id: this.currentRequestId,
          interruption_epoch: this.currentInterruptionEpoch,
        },
      },
    })
    this.responseActive = true
    this.setStatus('responding')
  }

  private emitAgentJob(
    job: PendingRealtimeAgentJob,
    status: CompanionJobStatus,
    data?: Record<string, unknown>,
  ): void {
    const eventType = {
      created: 'AgentJobCreated',
      running: 'AgentJobRunning',
      progress: 'AgentJobProgress',
      completed: 'AgentJobCompleted',
      failed: 'AgentJobFailed',
      cancelled: 'AgentJobCancelled',
      interrupted: 'AgentJobInterrupted',
    } as const
    job.revision += 1
    this.emit('companion-event', {
      version: 1,
      type: eventType[status],
      workspaceId: job.workspaceId,
      sessionId: job.sessionId,
      turnId: job.turnId,
      jobId: job.jobId,
      requestId: job.requestId,
      revision: job.revision,
      interruptionEpoch: job.interruptionEpoch,
      generationId: this.currentGenerationId,
      sequence: this.nextSequence(),
      source: 'voice',
      timestamp: Date.now(),
      status,
      ...(data ? { data } : {}),
    })
  }

  private abortPendingToolCalls(): void {
    for (const job of this.pendingAgentJobs.values()) {
      this.emitAgentJob(job, 'cancelled')
      job.controller.abort()
    }
    this.pendingAgentJobs.clear()
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
    if (this.currentTurnCancelled) return
    const userText = this.inputTranscript.trim()
    const assistantText = (this.assistantTranscript || this.assistantDeltaText).trim()
    if (!userText || !assistantText) return
    if (this.finalizeTimer !== null) {
      window.clearTimeout(this.finalizeTimer)
      this.finalizeTimer = null
    }
    this.emit('turn-complete', {
      turnId: this.currentTurnId,
      generationId: this.currentGenerationId,
      requestId: this.currentRequestId,
      sequence: this.nextSequence(),
      envelopeVersion: 1,
      userText,
      assistantText,
      model: this.model,
      elapsedMs: this.elapsedSinceSpeechEnd() ?? 0,
      workspaceId: this.workspaceId,
      sessionId: this.sessionId,
      interruptionEpoch: this.currentInterruptionEpoch,
      ...(this.delegatedActionEnvelope !== undefined
        ? { actionEnvelope: this.delegatedActionEnvelope }
        : {}),
    })
    this.resetTurn()
  }

  private resetTurn(): void {
    this.retireCurrentServerIdentities()
    if (this.finalizeTimer !== null) {
      window.clearTimeout(this.finalizeTimer)
      this.finalizeTimer = null
    }
    this.inputTranscript = ''
    this.inputTranscriptStableReported = false
    this.assistantTranscript = ''
    this.assistantDeltaText = ''
    this.responseDone = false
    this.currentTurnCancelled = false
    this.playbackReported = false
    this.speechEndedAt = null
    this.delegatedActionEnvelope = undefined
    this.currentTurnId = createTurnId()
    this.currentGenerationId = createTurnId()
    this.currentRequestId = `voice_${this.currentGenerationId}`
    this.eventSequence = 0
  }

  private acceptCreatedResponse(value: unknown): boolean {
    if (!isRecord(value)) return false
    const responseId = readString(value.id).trim()
    if (responseId && this.retiredResponseIds.has(responseId)) return false
    const metadata = isRecord(value.metadata) ? value.metadata : null
    const generationId = readString(metadata?.generation_id).trim()
    const turnId = readString(metadata?.turn_id).trim()
    const requestId = readString(metadata?.request_id).trim()
    const interruptionEpoch = Number(metadata?.interruption_epoch)
    const envelopeVersion = Number(metadata?.envelope_version)
    const mismatched = (
      envelopeVersion !== 1
      || generationId !== this.currentGenerationId
      || turnId !== this.currentTurnId
      || requestId !== this.currentRequestId
      || !Number.isFinite(interruptionEpoch)
      || interruptionEpoch !== this.currentInterruptionEpoch
    )
    if (mismatched) {
      this.rememberRetiredId(this.retiredResponseIds, responseId)
      return false
    }
    if (responseId) this.currentResponseId = responseId
    return true
  }

  private matchesCurrentResponse(event: RealtimeServerEvent): boolean {
    const response = isRecord(event.response) ? event.response : null
    const responseId = readString(event.response_id).trim() || readString(response?.id).trim()
    if (!responseId) return true
    if (this.retiredResponseIds.has(responseId)) return false
    if (this.currentResponseId && responseId !== this.currentResponseId) return false
    this.currentResponseId = responseId
    return true
  }

  private matchesCurrentInputItem(event: RealtimeServerEvent): boolean {
    const itemId = readString(event.item_id).trim()
    if (!itemId) return true
    if (this.retiredInputItemIds.has(itemId)) return false
    if (this.currentInputItemId && itemId !== this.currentInputItemId) return false
    this.currentInputItemId = itemId
    return true
  }

  private retireCurrentServerIdentities(): void {
    this.rememberRetiredId(this.retiredResponseIds, this.currentResponseId)
    this.rememberRetiredId(this.retiredInputItemIds, this.currentInputItemId)
    this.currentResponseId = ''
    this.currentInputItemId = ''
  }

  private rememberRetiredId(target: Set<string>, value: string): void {
    if (!value) return
    target.add(value)
    while (target.size > MAX_RETIRED_SERVER_IDS) {
      const oldest = target.values().next().value
      if (oldest === undefined) break
      target.delete(oldest)
    }
  }

  private currentScope(): RealtimeVoiceScope {
    return {
      workspaceId: this.workspaceId,
      sessionId: this.sessionId,
      interruptionEpoch: this.currentInterruptionEpoch,
      turnId: this.currentTurnId,
      generationId: this.currentGenerationId,
      requestId: this.currentRequestId,
      sequence: this.nextSequence(),
      envelopeVersion: 1,
    }
  }

  private nextSequence(): number {
    this.eventSequence += 1
    return this.eventSequence
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
    this.operationEpoch += 1
    this.abortPendingToolCalls()
    this.completedToolCallIds.clear()
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
    this.agentModel = ''
    this.petControlContext = null
    this.agentMcpEnabled = true
    this.agentWebSearchEnabled = false
    this.responseActive = false
    this.resetTurn()
    this.retiredResponseIds.clear()
    this.retiredInputItemIds.clear()
    this.pendingInputCommits = []
  }
}

export const realtimeVoiceSession = new RealtimeVoiceSession()
