import { computed, reactive, watch } from 'vue'
import type { MaybeRefOrGetter } from 'vue'
import { toValue } from 'vue'
import type { ChatMessage } from '@/../shared/types'

type SearchState = {
  visible: boolean
  query: string
  activeMatchIndex: number
}

type MessageSearchOptions = {
  messages: MaybeRefOrGetter<ChatMessage[]>
  roleLabel: (role: ChatMessage['role']) => string
  onMatchSelected: (messageIndex: number) => void
}

export function useMessageSearch({ messages, roleLabel, onMatchSelected }: MessageSearchOptions) {
  const state = reactive<SearchState>({
    visible: false,
    query: '',
    activeMatchIndex: -1,
  })
  const normalizedQuery = computed(() => state.query.trim().toLowerCase())
  const matches = computed(() => {
    const query = normalizedQuery.value
    if (!query) return []
    return toValue(messages)
      .map((message, index) => ({ message, index }))
      .filter(({ message }) => `${roleLabel(message.role)} ${message.content}`.toLowerCase().includes(query))
      .map(({ index }) => index)
  })
  const activeMessageIndex = computed(() => {
    if (!matches.value.length) return -1
    const activeIndex = Math.max(0, Math.min(state.activeMatchIndex, matches.value.length - 1))
    return matches.value[activeIndex] ?? -1
  })
  const resultLabel = computed(() => {
    if (!normalizedQuery.value || !matches.value.length) return '0/0'
    return `${Math.max(0, state.activeMatchIndex) + 1}/${matches.value.length}`
  })

  const open = () => {
    state.visible = true
  }

  const close = () => {
    state.visible = false
    state.query = ''
    state.activeMatchIndex = -1
  }

  const toggle = () => {
    if (state.visible) {
      close()
      return
    }
    open()
  }

  const jump = (direction: 1 | -1) => {
    const currentMatches = matches.value
    if (!currentMatches.length) return
    state.activeMatchIndex = state.activeMatchIndex < 0
      ? direction > 0 ? 0 : currentMatches.length - 1
      : (state.activeMatchIndex + direction + currentMatches.length) % currentMatches.length
    onMatchSelected(currentMatches[state.activeMatchIndex])
  }

  const handleGlobalKeydown = (event: KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
      event.preventDefault()
      open()
    }
  }

  watch(matches, (currentMatches) => {
    if (!state.visible || !normalizedQuery.value) {
      state.activeMatchIndex = -1
      return
    }
    state.activeMatchIndex = currentMatches.length ? 0 : -1
    if (currentMatches.length) onMatchSelected(currentMatches[0])
  })

  return {
    state,
    matches,
    activeMessageIndex,
    resultLabel,
    open,
    close,
    toggle,
    jump,
    handleGlobalKeydown,
  }
}
