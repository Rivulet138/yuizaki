import { ElMessage } from 'element-plus'
import { onMounted, onUnmounted, watch } from 'vue'
import type { PetExpressionMixPayload } from '@/../shared/pet-control'
import { legacyDirectiveToAvatarCommand, type AvatarAction, type AvatarCommand } from '@/../shared/avatar-command'
import { audioCapture } from '@/audio/audio-capture'
import { realtimeVoiceSession } from '@/audio/realtime-voice'
import { PetSentenceEmotionScheduler, type PetTtsPlaybackStartedDetail } from '@/pet-sentence-emotion-scheduler'
import { useChatStore } from '@/stores/chatStore'
import { petControl } from '@/utils/petControl'
import { chatClient, shortcutClient } from '@/api/client'
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
  let voiceRuntimeEpoch = getCompanionInterruptionEpoch()
  let realtimeLipSyncForwardingActive = false
  let avatarCommandSequence = 0
  const avatarCommandStreamId = `voice:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`
  const realtimeEventBridge = new RealtimeVoiceEventBridge(realtimeVoiceSession)
  const isCurrentRealtimeScope = (scope: { workspaceId: string; sessionId: string; interruptionEpoch: number }) =>
    matchesRealtimeVoiceScope(scope, {
      workspaceId: chatState.currentWorkspaceId,
      sessionId: chatState.currentSessionId,
      interruptionEpoch: getCompanionInterruptionEpoch(),
    })

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
      const expressionMixPayload: PetExpressionMixPayload | null =
        Array.isArray(expressionMix) && expressionMix.length > 0
          ? {
              expressions: expressionMix,
              parameterOverrides,
              intensity: payload.intensity,
              durationMs,
            }
          : Array.isArray(parameterOverrides) && parameterOverrides.length > 0
            ? {
                expressions: [],
                parameterOverrides,
                intensity: payload.intensity,
                durationMs,
              }
            : null
      const hasAvatarCommand = Boolean(payload.avatar_command && typeof payload.avatar_command === 'object')

      if (payload.model_id || payload.model_type) {
        await petControl.setModelSelection(payload.model_id ?? null, payload.model_type)
        await refreshPetControlContext()
      }

      if (payload.emotion_id) {
        if (!hasAvatarCommand && payload.model_type !== 'vrm') {
          await petControl.triggerEmotion(payload.emotion_id, {
            source: 'automation',
          })
        }
      }

      const motionGroup = payload.motion_group ?? payload.motion?.group
      const motionIndex = payload.motion_index ?? payload.motion?.index ?? 0
      if (hasAvatarCommand || payload.model_type === 'vrm') {
        const sequence = avatarCommandSequence
        avatarCommandSequence += 1
        const directive = {
          expressionMix: expressionMix ?? [],
          parameterOverrides: parameterOverrides ?? [],
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
        if (!payload.avatar_command && payload.emotion_id && command) {
          command.actions.unshift({
            type: 'affect',
            emotion: payload.emotion_id,
            intensity: payload.intensity ?? 1,
            decayMs: durationMs ?? 1800,
          } satisfies AvatarAction)
        }
        await petControl.triggerAvatarCommand(command, {
          source: 'automation',
        })
      } else if (motionGroup) {
        await petControl.triggerMotion(motionGroup, motionIndex, {
          source: 'automation',
        })
      }

      if (expressionMixPayload && !hasAvatarCommand && payload.model_type !== 'vrm') {
        await petControl.triggerExpressionMix(expressionMixPayload, {
          source: 'automation',
        })
      } else if (resolvedExpression && !hasAvatarCommand && payload.model_type !== 'vrm') {
        await petControl.triggerExpression(resolvedExpression, {
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
    const sessionContext = {
      workspaceId: chatState.currentWorkspaceId,
      sessionId: chatState.currentSessionId,
      mcpEnabled: chatStore.chatOptions.mcp_enabled,
      webSearchEnabled: chatStore.chatOptions.web_search_enabled,
      voiceMode: chatStore.chatOptions.voice_mode,
      vadEagerness: 'auto',
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

  const startMic = async () => {
    if (audioCapture.getIsRecording().value || activeVoiceTransport !== null) return
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
          vadEagerness: 'auto',
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
    onStartMic: startMic,
    onStopMic: stopMic,
    onToggleMic: toggleMic,
  })

  onMounted(() => {
    const socketClient = chatClient.getSocketClient()
    realtimeEventBridge.listen('status', ({ status }) => {
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
        if (!realtimeVoiceSession.isConnected() || realtimeVoiceSession.isConnectedFor({ workspaceId, sessionId })) return
        realtimeVoiceSession.close()
        activeVoiceTransport = null
        chatStore.setRealtimeRecording(false)
        chatStore.setRealtimePlayback(false)
        void publishCompanionRuntimeEvent({ source: 'voice', activity: 'idle' })
      },
    )
    watch(
      () => [chatStore.chatOptions.response_mode, chatStore.chatOptions.voice_mode] as const,
      ([responseMode, voiceMode], [previousResponseMode, previousVoiceMode]) => {
        if (responseMode === previousResponseMode && voiceMode === previousVoiceMode) return
        if (realtimeVoiceSession.isConnected()) realtimeVoiceSession.close()
        activeVoiceTransport = null
        chatStore.setRealtimeRecording(false)
        chatStore.setRealtimePlayback(false)
        void publishCompanionRuntimeEvent({ source: 'voice', activity: 'idle' })
        if (responseMode === 'instant') void prewarmRealtimeVoice()
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
    realtimeEventBridge.listen('playback-start', ({ elapsedMs }) => {
      chatStore.setRealtimePlayback(true)
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
      console.warn('[VoiceBridge] realtime voice error:', message)
    })
    void prewarmRealtimeVoice()
    voiceEventBridge.attach(window, shortcutClient)

    void refreshPetControlContext()
  })

  onUnmounted(() => {
    if (audioCapture.getIsRecording().value) {
      audioCapture.stop()
    }
    realtimeVoiceSession.close()
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
