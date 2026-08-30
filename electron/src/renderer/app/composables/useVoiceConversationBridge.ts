import { ElMessage } from 'element-plus'
import { onMounted, onUnmounted, watch } from 'vue'
import { legacyDirectiveToAvatarCommand, type AvatarCommand } from '@/../shared/avatar-command'
import { audioCapture } from '@/audio/audio-capture'
import { realtimeVoiceSession } from '@/audio/realtime-voice'
import { PetSentenceEmotionScheduler, type PetTtsPlaybackStartedDetail } from '@/pet-sentence-emotion-scheduler'
import { useChatStore } from '@/stores/chatStore'
import { petControl } from '@/utils/petControl'
import { chatClient, shortcutClient, systemClient } from '@/api/client'
import {
  getCompanionInterruptionEpoch,
  publishCompanionJobEvent,
  publishCompanionRuntimeEvent,
} from '../runtime/companionRuntime'
import { VoiceEventBridge } from '../runtime/voiceEventBridge'
import { matchesRealtimeVoiceScope, matchesRealtimeVoiceTurnScope, RealtimeVoiceEventBridge } from '../runtime/realtimeVoiceEventBridge'

interface PetControlPayload {
  emotion_id?: string
  motion_group?: string
  motion_index?: number
  expression_name?: string
  model_id?: string | null
  model_type?: 'live2d' | 'vrm'
  expression_mix?: Array<{ expression: string; weight?: number }>
  parameter_overrides?: Array<{ id: string; value: number; weight?: number }>
  expressionMix?: Array<{ expression: string; weight?: number }>
  parameterOverrides?: Array<{ id: string; value: number; weight?: number }>
  motion?: { group: string; index?: number }
  intensity?: number
  duration_ms?: number
  durationMs?: number
  avatar_command?: unknown
}

const LIVE2D_PARAMETER_CONTEXT = [
  { id: 'ParamAngleX', min: -30, max: 30 },
  { id: 'ParamAngleY', min: -30, max: 30 },
  { id: 'ParamAngleZ', min: -30, max: 30 },
  { id: 'ParamBodyAngleX', min: -15, max: 15 },
  { id: 'ParamBodyAngleY', min: -10, max: 10 },
  { id: 'ParamBodyAngleZ', min: -15, max: 15 },
  { id: 'ParamEyeBallX', min: -1, max: 1 },
  { id: 'ParamEyeBallY', min: -1, max: 1 },
  { id: 'ParamBrowLY', min: -1, max: 1 },
  { id: 'ParamBrowRY', min: -1, max: 1 },
  { id: 'ParamBrowLAngle', min: -30, max: 30 },
  { id: 'ParamBrowRAngle', min: -30, max: 30 },
  { id: 'ParamBrowLForm', min: -1, max: 1 },
  { id: 'ParamBrowRForm', min: -1, max: 1 },
  { id: 'ParamCheek', min: 0, max: 1 },
  { id: 'ParamMouthOpenY', min: 0, max: 1 },
  { id: 'ParamMouthForm', min: -1, max: 1 },
]

export function useVoiceConversationBridge() {
  const chatStore = useChatStore()
  const chatState = chatStore.state
  const sentenceEmotionScheduler = new PetSentenceEmotionScheduler()
  const audioCaptureState = audioCapture.getStatus()
  let activeVoiceTransport: 'pipeline' | 'realtime' | null = null
  let mounted = false
  let voiceRuntimeEpoch = getCompanionInterruptionEpoch()
  let realtimeLipSyncForwardingActive = false
  let avatarCommandSequence = 0
  let diagnosticsRunId: string | null = null
  let diagnosticsRunPromise: Promise<void> | null = null
  let diagnosticsRunGeneration = 0
  const avatarCommandStreamId = `voice:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`
  const realtimeEventBridge = new RealtimeVoiceEventBridge(realtimeVoiceSession, (sample) => {
    if (!mounted) return
    const runId = sample.runId
    if (!runId) return
    if (sample.scope && !isCurrentRealtimeScope(sample.scope)) return
    // Persist only bounded timing/recovery metadata; never send transcript or audio.
    void systemClient.recordVoiceDiagnosticSample({
      stage: sample.stage,
      latency_ms: sample.latencyMs,
      ok: sample.ok,
      recovered: sample.recovered,
      recovery_latency_ms: sample.recoveryLatencyMs,
      playback_underruns: sample.playbackUnderruns,
      run_id: runId,
    }).catch(() => undefined)
    if (sample.stage === 'interruption' || sample.stage === 'interrupt_ack') {
      void systemClient.recordVoiceComfort({
        scenario: 'deliberate_interrupt',
        run_id: runId,
        ...(sample.stage === 'interruption'
          ? { stop_audio_latency_ms: sample.latencyMs }
          : { interrupt_ack_latency_ms: sample.latencyMs }),
      }).catch(() => undefined)
    }
  })
  const isCurrentRealtimeScope = (scope: { workspaceId: string; sessionId: string; interruptionEpoch: number }) =>
    matchesRealtimeVoiceScope(scope, {
      workspaceId: chatState.currentWorkspaceId,
      sessionId: chatState.currentSessionId,
      interruptionEpoch: getCompanionInterruptionEpoch(),
    })

  const createDiagnosticsRunId = (): string =>
    `voice-ui-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`

  const beginDiagnosticsRun = async (): Promise<void> => {
    const generation = ++diagnosticsRunGeneration
    const nextRunId = createDiagnosticsRunId()
    diagnosticsRunId = nextRunId
    realtimeEventBridge.setDiagnosticRunId(nextRunId)
    try {
      const result = await systemClient.beginVoiceDiagnosticsRun(nextRunId)
      if (generation !== diagnosticsRunGeneration || result.run_id !== nextRunId) return
    } catch (error) {
      if (generation === diagnosticsRunGeneration) {
        diagnosticsRunId = null
        realtimeEventBridge.setDiagnosticRunId(null)
      }
      console.debug('[VoiceBridge] diagnostics run unavailable:', error)
    }
  }

  const queueDiagnosticsRun = (): Promise<void> => {
    const task = beginDiagnosticsRun()
    const trackedTask = task.finally(() => {
      if (diagnosticsRunPromise === trackedTask) diagnosticsRunPromise = null
    })
    diagnosticsRunPromise = trackedTask
    return trackedTask
  }

  const ensureDiagnosticsRun = async (): Promise<void> => {
    if (diagnosticsRunId) return
    if (!diagnosticsRunPromise) queueDiagnosticsRun()
    await diagnosticsRunPromise
  }

  const rotateDiagnosticsRun = async (): Promise<void> => {
    diagnosticsRunGeneration += 1
    diagnosticsRunId = null
    realtimeEventBridge.setDiagnosticRunId(null)
    const previousRun = diagnosticsRunPromise
    if (previousRun) await previousRun
    if (!mounted) return
    await queueDiagnosticsRun()
  }

  const refreshPetControlContext = async (): Promise<void> => {
    try {
      const [catalog, runtime] = await Promise.all([
        petControl.getCatalog(),
        petControl.getAvatarCapabilities().catch(() => null),
      ])
      const models = catalog.models.map((model) => ({ id: model.id, type: model.type }))
      const emotions = Array.from(new Set(catalog.models.flatMap((model) => model.emotions.map((emotion) => emotion.id))))
      const motionGroups = Array.from(new Set(catalog.models.flatMap((model) => model.motions.map((motion) => motion.group))))
      const motionOptions = catalog.models.flatMap((model) => model.motions.map((motion) => ({ group: motion.group, index: motion.index })))
      const expressions = Array.from(new Set(catalog.models.flatMap((model) => model.expressions.map((expression) => expression.name))))
      const activeModel = catalog.models.find((model) => model.id === catalog.activeModelId) ?? catalog.models[0]
      const capabilities = runtime?.success ? runtime.capabilities : null
      const runtimeModel = capabilities?.modelId ? { id: capabilities.modelId, type: capabilities.modelType } : null
      const runtimeModels = runtimeModel && !models.some((model) => model.id === runtimeModel.id) ? [...models, runtimeModel] : models
      const avatarPrompt = capabilities
        ? (activeModel?.id === capabilities.modelId ? activeModel.promptContext ?? '' : '')
        : activeModel?.promptContext ?? ''

      chatStore.setPetControlContext({
        models: runtimeModels,
        emotions,
        motionGroups: capabilities?.motions.map((motion) => motion.group) ?? motionGroups,
        motionOptions: capabilities?.motions.map((motion) => ({ group: motion.group, index: motion.index })) ?? motionOptions,
        expressions: capabilities?.expressions ?? expressions,
        parameters: capabilities?.parameters.map((parameter) => ({ id: parameter.id, min: parameter.min, max: parameter.max })) ?? LIVE2D_PARAMETER_CONTEXT,
        ...(capabilities ? {
          capabilityRevision: capabilities.revision,
          modelType: capabilities.modelType,
          modelId: capabilities.modelId,
          actions: capabilities.actions,
          viseme: capabilities.actions.viseme,
        } : {}),
        avatarPrompt,
      })
    } catch (error) {
      console.warn('[LLM Pet Control] failed to load pet control context:', error)
    }
  }

  const onLlmControl = async (event: Event) => {
    if (chatStore.chatOptions.pet_link_enabled === false) return
    const payload = (event as CustomEvent<PetControlPayload>).detail
    if (!payload) return

    try {
      const primaryExpressionFromMix = Array.isArray(payload.expression_mix)
        ? [...payload.expression_mix].filter((item) => item?.expression).sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1))[0]?.expression
        : Array.isArray(payload.expressionMix)
          ? [...payload.expressionMix].filter((item) => item?.expression).sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1))[0]?.expression
          : undefined

      const resolvedExpression = payload.expression_name || primaryExpressionFromMix
      const expressionMix = payload.expression_mix ?? payload.expressionMix
      const parameterOverrides = payload.parameter_overrides ?? payload.parameterOverrides
      const durationMs = payload.duration_ms ?? payload.durationMs
      const expressionMixItems = Array.isArray(expressionMix)
        ? expressionMix.filter((item) => Boolean(item?.expression))
        : []
      const normalizedExpressionMix = expressionMixItems.length > 0
        ? expressionMixItems
        : resolvedExpression
          ? [{ expression: resolvedExpression, weight: payload.intensity ?? 1 }]
          : []
      const normalizedParameterOverrides = Array.isArray(parameterOverrides)
        ? parameterOverrides.filter((item) => Boolean(item?.id) && Number.isFinite(item?.value))
        : []
      const hasAvatarCommand = Boolean(payload.avatar_command && typeof payload.avatar_command === 'object')

      if (payload.model_id || payload.model_type) {
        await petControl.setModelSelection(payload.model_id ?? null, payload.model_type)
        await refreshPetControlContext()
      }

      const motionGroup = payload.motion_group ?? payload.motion?.group
      const motionIndex = payload.motion_index ?? payload.motion?.index ?? 0
      const hasLegacyEmbodiment = Boolean(
        payload.emotion_id
        || motionGroup
        || normalizedExpressionMix.length > 0
        || normalizedParameterOverrides.length > 0,
      )
      if (hasAvatarCommand || hasLegacyEmbodiment) {
        const sequence = avatarCommandSequence
        avatarCommandSequence += 1
        const directive = {
          expressionMix: normalizedExpressionMix,
          parameterOverrides: normalizedParameterOverrides,
          ...(motionGroup ? { motion: { group: motionGroup, index: motionIndex } } : {}),
          intensity: payload.intensity ?? 1,
          durationMs: durationMs ?? 1800,
        }
        const command =
          payload.avatar_command && typeof payload.avatar_command === 'object'
            ? (payload.avatar_command as AvatarCommand)
            : legacyDirectiveToAvatarCommand(directive, {
                id: `agent-avatar-${Date.now()}-${sequence}`,
                streamId: avatarCommandStreamId,
                sequence,
                issuedAt: Date.now(),
                capabilityRevision: chatStore.getPetControlContext()?.capabilityRevision,
                interrupt: 'replace',
              })
        if (!payload.avatar_command && payload.emotion_id) {
          command.actions.unshift({
            type: 'affect',
            emotion: payload.emotion_id,
            intensity: payload.intensity ?? 1,
            decayMs: durationMs ?? 1800,
          })
        }
        await petControl.triggerAvatarCommand(command, {
          source: 'automation',
        })
      }

      window.dispatchEvent(
        new CustomEvent('pet:llm-control-applied', {
          detail: {
            emotion_id: payload.emotion_id,
            motion_group: payload.motion_group,
            motion_index: payload.motion_index,
            expression_name: resolvedExpression,
            model_id: payload.model_id,
            model_type: payload.model_type,
            parameter_overrides: payload.parameter_overrides,
            intensity: payload.intensity,
            duration_ms: durationMs,
          },
        }),
      )
    } catch (error) {
      console.warn('[LLM Pet Control] failed to apply pet control payload:', payload, error)
    }
  }

  const onAudioStarted = (event: Event) => {
    chatState.isTTSPlaying = true
    chatState.isSpeaking = true
    const detail = (event as CustomEvent<PetTtsPlaybackStartedDetail>).detail
    if (detail?.petLinkEnabled === false) {
      sentenceEmotionScheduler.cancel()
      return
    }
    sentenceEmotionScheduler.schedule(detail?.sentenceEmotionCues ?? [], {
      text: detail?.text,
      audioDurationMs: detail?.durationMs,
    })
  }

  const stopAudioPlaybackState = () => {
    chatState.isTTSPlaying = false
    chatState.isSpeaking = false
    sentenceEmotionScheduler.cancel()
  }

  const interruptRealtimeVoice = () => {
    realtimeVoiceSession.interrupt()
  }

  const prewarmRealtimeVoice = async (microphonePermissionKnown = false) => {
    await ensureDiagnosticsRun()
    if (!diagnosticsRunId) return
    const sessionContext = {
      workspaceId: chatState.currentWorkspaceId,
      sessionId: chatState.currentSessionId,
      mcpEnabled: chatStore.chatOptions.mcp_enabled,
      webSearchEnabled: chatStore.chatOptions.web_search_enabled,
      voiceMode: chatStore.chatOptions.voice_mode,
      vadEagerness: chatStore.chatOptions.vad_eagerness,
      audioInputDeviceId: chatStore.chatOptions.audio_input_device_id,
      petControlContext: chatStore.getPetControlContext(),
    }
    if (
      chatStore.chatOptions.response_mode !== 'instant' ||
      realtimeVoiceSession.isConnectedFor(sessionContext) ||
      activeVoiceTransport !== null
    )
      return
    try {
      if (!microphonePermissionKnown) {
        if (!navigator.permissions?.query) return
        const permission = await navigator.permissions.query({
          name: 'microphone' as PermissionName,
        })
        if (permission.state !== 'granted') return
      }
      await realtimeVoiceSession.connect(sessionContext)
      if (!mounted) {
        realtimeVoiceSession.close()
        return
      }
      if (chatStore.chatOptions.voice_mode === 'continuous') {
        activeVoiceTransport = 'realtime'
        chatStore.setRealtimeRecording(true, realtimeVoiceSession.getCurrentTurnIdentity())
        if (chatStore.chatOptions.pet_link_enabled !== false) {
          void publishCompanionRuntimeEvent({ source: 'voice', activity: 'listening', interruptionEpoch: voiceRuntimeEpoch })
        }
      }
    } catch (error) {
      console.debug('[VoiceBridge] realtime voice prewarm skipped:', error)
    }
  }

  const stopMic = () => {
    if (activeVoiceTransport === 'realtime') {
      if (realtimeVoiceSession.isContinuousMode()) realtimeVoiceSession.stopContinuous()
      else realtimeVoiceSession.stopPushToTalk()
      activeVoiceTransport = null
      chatStore.setRealtimeRecording(false)
      return
    }
    if (activeVoiceTransport === 'pipeline' || audioCapture.getIsRecording().value) {
      audioCapture.stop()
      activeVoiceTransport = null
      void prewarmRealtimeVoice(true)
    }
  }

  const retryRealtimeVoice = async () => {
    if (!mounted || chatStore.chatOptions.response_mode !== 'instant') return
    if (audioCapture.getIsRecording().value || chatState.isTTSPlaying) return
    realtimeVoiceSession.close()
    activeVoiceTransport = null
    chatStore.setRealtimeStatus('connecting')
    await prewarmRealtimeVoice(true)
  }

  const startMic = async () => {
    if (audioCapture.getIsRecording().value || activeVoiceTransport !== null) return
    await ensureDiagnosticsRun()
    const socketClient = chatClient.getSocketClient()

    if ((chatState.isGenerating || chatState.isTTSPlaying) && realtimeVoiceSession.getStatus() !== 'responding') {
      chatStore.interrupt()
    }
    voiceRuntimeEpoch = getCompanionInterruptionEpoch()

    if (
      chatStore.chatOptions.response_mode === 'instant' &&
      realtimeVoiceSession.isConnectedFor({
        workspaceId: chatState.currentWorkspaceId,
        sessionId: chatState.currentSessionId,
        voiceMode: chatStore.chatOptions.voice_mode,
        audioInputDeviceId: chatStore.chatOptions.audio_input_device_id,
      })
    ) {
      try {
        await realtimeVoiceSession.startPushToTalk({
          workspaceId: chatState.currentWorkspaceId,
          sessionId: chatState.currentSessionId,
          interruptionEpoch: voiceRuntimeEpoch,
          mcpEnabled: chatStore.chatOptions.mcp_enabled,
          webSearchEnabled: chatStore.chatOptions.web_search_enabled,
        voiceMode: chatStore.chatOptions.voice_mode,
        vadEagerness: chatStore.chatOptions.vad_eagerness,
        audioInputDeviceId: chatStore.chatOptions.audio_input_device_id,
        petControlContext: chatStore.getPetControlContext(),
        })
        activeVoiceTransport = 'realtime'
        chatStore.setRealtimeRecording(true, realtimeVoiceSession.getCurrentTurnIdentity())
        if (chatStore.chatOptions.pet_link_enabled !== false) {
          void publishCompanionRuntimeEvent({
            source: 'voice',
            activity: 'listening',
            interruptionEpoch: voiceRuntimeEpoch,
          })
        }
        return
      } catch (error) {
        console.warn('[VoiceBridge] realtime voice unavailable, falling back:', error)
        ElMessage.warning('即时语音不可用，已切换到本地语音链路')
      }
    } else if (chatStore.chatOptions.response_mode === 'instant') {
      console.info('[VoiceBridge] realtime voice is warming; using the local pipeline for this turn')
    }

    if (!socketClient.isConnected()) {
      ElMessage.warning('实时通道未连接，无法开始语音输入')
      return
    }
    try {
      await audioCapture.start({
        sessionId: chatState.currentSessionId,
        interruptionEpoch: voiceRuntimeEpoch,
        deviceId: chatStore.chatOptions.audio_input_device_id,
      })
      activeVoiceTransport = 'pipeline'
    } catch {
      ElMessage.error(audioCaptureState.error || '麦克风启动失败')
    }
  }

  const toggleMic = async () => {
    if (audioCapture.getIsRecording().value || activeVoiceTransport !== null) {
      stopMic()
      return
    }
    await startMic()
  }

  const voiceEventBridge = new VoiceEventBridge({
    onLlmControl,
    onAudioStarted,
    onAudioEnded: stopAudioPlaybackState,
    onTtsStop: stopAudioPlaybackState,
    onRealtimeInterrupt: interruptRealtimeVoice,
    onRealtimeReconnect: retryRealtimeVoice,
    onStartMic: startMic,
    onStopMic: stopMic,
    onToggleMic: toggleMic,
  })

  onMounted(() => {
    mounted = true
    const socketClient = chatClient.getSocketClient()
    realtimeEventBridge.listen('status', ({ status }) => {
      chatStore.setRealtimeStatus(status)
      if (status === 'recording') {
        chatStore.setRealtimeRecording(true, realtimeVoiceSession.getCurrentTurnIdentity())
        if (chatStore.chatOptions.pet_link_enabled !== false) {
          void publishCompanionRuntimeEvent({ source: 'voice', activity: 'listening', interruptionEpoch: voiceRuntimeEpoch })
        }
        return
      }
      if (status === 'responding') {
        chatState.isGenerating = true
        if (chatStore.chatOptions.pet_link_enabled !== false) {
          void publishCompanionRuntimeEvent({
            source: 'voice',
            activity: 'thinking',
            interruptionEpoch: voiceRuntimeEpoch,
          })
        }
        return
      }
      if (status === 'ready') {
        const continuousListening = realtimeVoiceSession.isContinuousMode() && realtimeVoiceSession.isMicrophoneActive()
        chatStore.setRealtimeRecording(continuousListening, continuousListening ? realtimeVoiceSession.getCurrentTurnIdentity() : undefined)
        chatState.isGenerating = false
        if (chatStore.chatOptions.pet_link_enabled !== false) {
          void publishCompanionRuntimeEvent({
            source: 'voice',
            activity: continuousListening ? 'listening' : 'idle',
            interruptionEpoch: voiceRuntimeEpoch,
          })
        }
        return
      }
      if (status === 'error' || status === 'closed') {
        if (activeVoiceTransport === 'realtime') activeVoiceTransport = null
        chatStore.setRealtimeRecording(false)
        chatStore.setRealtimePlayback(false)
        chatState.isGenerating = false
      }
    })
    realtimeEventBridge.listen('input-partial', (payload) => {
      if (!isCurrentRealtimeScope(payload)) return
      const { text } = payload
      chatStore.applyRealtimeInputPartial(text)
    })
    realtimeEventBridge.listen('speech-start', () => {
      if (chatStore.chatOptions.pet_link_enabled !== false) {
        void publishCompanionRuntimeEvent({ source: 'voice', activity: 'listening', interruptionEpoch: voiceRuntimeEpoch })
      }
    })
    realtimeEventBridge.listen('assistant-delta', (payload) => {
      if (!isCurrentRealtimeScope(payload)) return
      const { text } = payload
      chatStore.applyRealtimeAssistantDelta(text)
    })
    realtimeEventBridge.listen('turn-complete', (turn) => {
      const identity = chatStore.getCurrentRealtimeIdentity()
      if (!identity || !matchesRealtimeVoiceTurnScope(turn, {
        workspaceId: chatState.currentWorkspaceId,
        sessionId: chatState.currentSessionId,
        interruptionEpoch: getCompanionInterruptionEpoch(),
        ...identity,
      })) return
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_turn_complete', {
          elapsedMs: turn.elapsedMs,
          sessionId: turn.sessionId,
          generationId: turn.generationId,
        })
      }
      void chatStore.completeRealtimeTurn(turn)
    })
    realtimeEventBridge.listen('agent-result', ({ petControl, ...scope }) => {
      if (!isCurrentRealtimeScope(scope)) return
      if (!petControl || typeof petControl !== 'object') return
      window.dispatchEvent(new CustomEvent('pet:llm-control', { detail: petControl }))
    })
    watch(
      () => [chatState.currentWorkspaceId, chatState.currentSessionId] as const,
      ([workspaceId, sessionId], [previousWorkspaceId, previousSessionId]) => {
        if (workspaceId === previousWorkspaceId && sessionId === previousSessionId) return
        const wasConnectedForCurrentContext = realtimeVoiceSession.isConnectedFor({
          workspaceId,
          sessionId,
          audioInputDeviceId: chatStore.chatOptions.audio_input_device_id,
        })
        if (!wasConnectedForCurrentContext) realtimeVoiceSession.close()
        activeVoiceTransport = null
        chatStore.setRealtimeRecording(false)
        chatStore.setRealtimePlayback(false)
        void publishCompanionRuntimeEvent({ source: 'voice', activity: 'idle' })
        void rotateDiagnosticsRun().then(() => {
          if (chatStore.chatOptions.response_mode === 'instant') void prewarmRealtimeVoice()
        })
      },
    )
    watch(
      () => [chatStore.chatOptions.response_mode, chatStore.chatOptions.voice_mode, chatStore.chatOptions.vad_eagerness, chatStore.chatOptions.audio_input_device_id] as const,
      ([responseMode, voiceMode, vadEagerness, audioInputDeviceId], [previousResponseMode, previousVoiceMode, previousVadEagerness, previousAudioInputDeviceId]) => {
        if (responseMode === previousResponseMode && voiceMode === previousVoiceMode && vadEagerness === previousVadEagerness && audioInputDeviceId === previousAudioInputDeviceId) return
        if (realtimeVoiceSession.isConnected()) realtimeVoiceSession.close()
        activeVoiceTransport = null
        chatStore.setRealtimeRecording(false)
        chatStore.setRealtimePlayback(false)
        void publishCompanionRuntimeEvent({ source: 'voice', activity: 'idle' })
        void rotateDiagnosticsRun().then(() => {
          if (responseMode === 'instant') void prewarmRealtimeVoice()
        })
      },
    )
    realtimeEventBridge.listen('companion-event', (event) => {
      void publishCompanionJobEvent(event, {
        workspaceId: chatState.currentWorkspaceId,
        sessionId: chatState.currentSessionId,
        interruptionEpoch: getCompanionInterruptionEpoch(),
      })
    })
    realtimeEventBridge.listen('connect', ({ elapsedMs }) => {
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_connect', { elapsedMs })
      }
    })
    realtimeEventBridge.listen('response-start', ({ elapsedMs }) => {
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_speech_to_response', {
          elapsedMs,
        })
      }
    })
    realtimeEventBridge.listen('transcript-stable', ({ elapsedMs }) => {
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_transcript_stable', { elapsedMs })
      }
    })
    realtimeEventBridge.listen('empty-input', () => {
      const runId = diagnosticsRunId
      if (!runId) return
      void systemClient.recordVoiceComfort({
        scenario: 'empty_asr',
        continuous_turn_completed: false,
        run_id: runId,
      }).catch(() => undefined)
    })
    realtimeEventBridge.listen('comfort-signal', (payload) => {
      // Comfort observations are session-scoped just like transcripts. A
      // delayed signal from a closed/replaced realtime session must not
      // contaminate the current run's comfort metrics.
      if (!mounted || !isCurrentRealtimeScope(payload)) return
      const { signal, source, confidence, durationMs } = payload
      const runId = diagnosticsRunId
      if (!runId) return
      void systemClient.recordVoiceComfortSignal({
        signal,
        source,
        confidence,
        ...(durationMs === undefined ? {} : { duration_ms: durationMs }),
        run_id: runId,
      }).catch(() => undefined)
    })
    realtimeEventBridge.listen('playback-start', ({ elapsedMs }) => {
      const runId = diagnosticsRunId
      chatStore.setRealtimePlayback(true)
      if (runId) {
        void systemClient.recordVoiceComfort({
          scenario: 'first_audio',
          first_audio_latency_ms: elapsedMs,
          run_id: runId,
        }).catch(() => undefined)
      }
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_speech_to_playback', {
          elapsedMs,
        })
      }
    })
    realtimeEventBridge.listen('playback-end', () => {
      chatStore.setRealtimePlayback(false)
    })
    realtimeEventBridge.listen('playback-stop', ({ elapsedMs }) => {
      chatStore.setRealtimePlayback(false)
      if (socketClient.isConnected()) socketClient.sendClientTiming('realtime_playback_stop', { elapsedMs })
    })
    realtimeEventBridge.listen('playback-recovery', ({ elapsedMs, ok, recovered, recoveryLatencyMs, playbackUnderruns }) => {
      if (!ok) chatStore.setRealtimePlayback(false)
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_playback_recovery', {
          elapsedMs,
          ok,
          recovered,
          recoveryLatencyMs,
          playbackUnderruns,
        })
      }
    })
    realtimeEventBridge.listen('provider-cancel', ({ elapsedMs }) => {
      if (socketClient.isConnected()) socketClient.sendClientTiming('realtime_provider_cancel', { elapsedMs })
    })
    realtimeEventBridge.listen('lip-sync-level', ({ level, active }) => {
      const petLinkEnabled = chatStore.chatOptions.pet_link_enabled !== false
      if (!petLinkEnabled) {
        if (realtimeLipSyncForwardingActive) {
          window.petApi?.pet.setRealtimeLipSync(0, false)
          realtimeLipSyncForwardingActive = false
        }
        return
      }
      if (active) {
        window.petApi?.pet.setRealtimeLipSync(level, true)
        realtimeLipSyncForwardingActive = true
      } else if (realtimeLipSyncForwardingActive) {
        window.petApi?.pet.setRealtimeLipSync(0, false)
        realtimeLipSyncForwardingActive = false
      }
    })
    realtimeEventBridge.listen('interrupt-ack', ({ elapsedMs }) => {
      chatStore.setRealtimePlayback(false)
      if (socketClient.isConnected()) {
        socketClient.sendClientTiming('realtime_interrupt_ack', { elapsedMs })
      }
    })
    realtimeEventBridge.listen('error', ({ message, fatal }) => {
      if (fatal) chatStore.setRealtimeError(message)
      else chatStore.setRealtimeStatus('error')
      console.warn('[VoiceBridge] realtime voice error:', message)
    })
    void ensureDiagnosticsRun().then(() => {
      if (chatStore.chatOptions.response_mode === 'instant') void prewarmRealtimeVoice()
    })
    voiceEventBridge.attach(window, shortcutClient)

    void refreshPetControlContext()
  })

  onUnmounted(() => {
    mounted = false
    if (audioCapture.getIsRecording().value) {
      audioCapture.stop()
    }
    realtimeVoiceSession.close()
    diagnosticsRunGeneration += 1
    diagnosticsRunId = null
    realtimeEventBridge.setDiagnosticRunId(null)
    if (realtimeLipSyncForwardingActive) {
      window.petApi?.pet.setRealtimeLipSync(0, false)
      realtimeLipSyncForwardingActive = false
    }
    realtimeEventBridge.detach()
    voiceEventBridge.detach()
    sentenceEmotionScheduler.cancel()
  })

  return {
    startMic,
    stopMic,
    toggleMic,
  }
}
