import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { audioCapture } from '@/audio/audio-capture'
import { useChatStore } from '@/stores/chatStore'
import { chatClient } from '@/api/client'

export function useChatDomain() {
  const chatStore = useChatStore()
  const chatState = chatStore.state
  const socketClient = chatClient.getSocketClient()
  const socketDomain = {
    status: { value: socketClient.isConnected() ? 'connected' : 'offline' as const },
    error: { value: null as string | null },
    isConnected: socketClient.connected,
  }

  const inputText = ref('')
  const isRecording = audioCapture.getIsRecording()
  const audioCaptureState = audioCapture.getStatus()

  function stopMic() {
    if (!audioCapture.getIsRecording().value) return
    audioCapture.stop()
  }

  async function startMic() {
    if (audioCapture.getIsRecording().value) return
    const socketClient = chatClient.getSocketClient()
    if (!socketClient.isConnected()) {
      ElMessage.warning('实时通道未连接，无法开始语音输入')
      return
    }

    if (chatState.isGenerating || chatState.isTTSPlaying) {
      chatStore.interrupt()
    }

    try {
      await audioCapture.start()
    } catch {
      ElMessage.error(audioCaptureState.error || '麦克风启动失败')
    }
  }

  async function toggleMic() {
    if (audioCapture.getIsRecording().value) {
      stopMic()
      return
    }
    await startMic()
  }

  function sendText() {
    const text = inputText.value.trim()
    if (!text) return
    chatStore.sendChat(text)
    inputText.value = ''
  }

  function handleInterrupt() {
    chatStore.interrupt()
  }

  return {
    socketDomain,
    chatState,
    inputText,
    isRecording,
    audioCaptureState,
    startMic,
    stopMic,
    toggleMic,
    sendText,
    handleInterrupt,
  }
}
