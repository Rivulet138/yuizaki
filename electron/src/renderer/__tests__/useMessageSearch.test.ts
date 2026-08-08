import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '../shared/types'
import { useMessageSearch } from '../domains/chat/composables/useMessageSearch'

const messages = ref<ChatMessage[]>([
  { role: 'user', content: 'Prepare the Live2D model.' },
  { role: 'assistant', content: 'The model is ready.' },
  { role: 'user', content: 'Show status.' },
])

const setup = () => {
  const selected: number[] = []
  const search = useMessageSearch({
    messages,
    roleLabel: (role) => role === 'assistant' ? 'Assistant' : 'User',
    onMatchSelected: (index) => selected.push(index),
  })
  return { search, selected }
}

describe('useMessageSearch', () => {
  it('finds message content and roles, then cycles through matches', async () => {
    const { search, selected } = setup()
    search.open()
    search.state.query = 'model'
    await nextTick()

    expect(search.matches.value).toEqual([0, 1])
    expect(search.activeMessageIndex.value).toBe(0)
    expect(search.resultLabel.value).toBe('1/2')
    expect(selected).toEqual([0])

    search.jump(1)
    expect(search.activeMessageIndex.value).toBe(1)
    expect(search.resultLabel.value).toBe('2/2')
    expect(selected).toEqual([0, 1])

    search.jump(1)
    expect(search.activeMessageIndex.value).toBe(0)
  })

  it('opens from the standard find shortcut and clears state on close', async () => {
    const { search } = setup()
    const event = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, cancelable: true })
    search.handleGlobalKeydown(event)
    search.state.query = 'user'
    await nextTick()

    expect(event.defaultPrevented).toBe(true)
    expect(search.state.visible).toBe(true)
    expect(search.matches.value).toEqual([0, 2])

    search.close()
    expect(search.state).toMatchObject({ visible: false, query: '', activeMatchIndex: -1 })
    expect(search.resultLabel.value).toBe('0/0')
  })
})
