import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatMessageList from '../domains/chat/components/ChatMessageList.vue'

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
})

const mountList = (props: Record<string, unknown> = {}) => mount(ChatMessageList, {
  props: {
    messages: [
      { id: 11, role: 'user', content: '你好', timestamp: '2026-08-07T09:00:00.000Z' },
      { id: 12, role: 'assistant', content: '<think>内部推理</think>回答正文', reasoning: '另一段内部推理' },
    ],
    contextStartIndex: 1,
    currentText: '',
    isGenerating: false,
    pendingAssistantLabel: '等待模型输出',
    editingMessage: { index: -1, content: '', saving: false },
    searchMatches: [1],
    activeSearchMessageIndex: 1,
    messageTranslatingIndex: null,
    contextMenu: { visible: false, x: 0, y: 0, index: -1 },
    canRegenerateFromIndex: () => true,
    ...props,
  },
  global: {
    stubs: {
      'el-button': ElButtonStub,
      'el-input': { template: '<textarea />' },
      'el-tooltip': { template: '<span><slot /></span>' },
      'el-icon': { template: '<i><slot /></i>' },
    },
  },
})

describe('ChatMessageList', () => {
  it('renders conversation state and emits message commands', async () => {
    const wrapper = mountList()

    expect(wrapper.text()).toContain('你好')
    expect(wrapper.text()).toContain('回答正文')
    expect(wrapper.text()).not.toContain('内部推理')
    expect(wrapper.text()).not.toContain('另一段内部推理')
    expect(wrapper.find('.message-reasoning').exists()).toBe(false)
    expect(wrapper.text()).toContain('从这里开始上下文')
    expect(wrapper.find('[data-message-index="1"]').classes()).toContain('is-search-active')

    await wrapper.find('[aria-label="复制消息"]').trigger('click')
    await wrapper.find('[aria-label="引用消息"]').trigger('click')
    await wrapper.find('[aria-label="重新生成回复"]').trigger('click')
    await wrapper.find('[aria-label="从此处创建分支"]').trigger('click')

    expect(wrapper.emitted('copy')?.[0]).toEqual(['你好'])
    expect(wrapper.emitted('quote')?.[0]).toEqual([{ id: 11, role: 'user', content: '你好', timestamp: '2026-08-07T09:00:00.000Z' }])
    expect(wrapper.emitted('regenerate')?.[0]).toEqual([1])
    expect(wrapper.emitted('create-branch')?.[0]).toEqual([0, { id: 11, role: 'user', content: '你好', timestamp: '2026-08-07T09:00:00.000Z' }])
  })

  it('keeps streaming, pending, and edit controls explicit without exposing hidden reasoning', async () => {
    const streaming = mountList({
      currentText: '<think>先分析</think>流式回答',
      isGenerating: true,
    })

    expect(streaming.text()).toContain('流式回答')
    expect(streaming.text()).not.toContain('先分析')
    expect(streaming.text()).not.toContain('思考过程')
    expect(streaming.find('.message-reasoning-hidden').exists()).toBe(false)

    const pending = mountList({ currentText: '', isGenerating: true })
    expect(pending.text()).toContain('等待模型输出')

    const editing = mountList({
      editingMessage: { index: 0, content: '修改后的消息', saving: false },
    })
    const buttons = editing.findAll('.message-edit-actions button')
    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')

    expect(editing.emitted('cancel-edit')).toEqual([[]])
    expect(editing.emitted('save-edit')).toEqual([[false], [true]])
  })

  it('shows agent steps and memory provenance through compact disclosures', async () => {
    const wrapper = mountList({
      messages: [{
        id: 21,
        role: 'assistant',
        content: 'Answer',
        agentSteps: [{ id: 'step-1', title: 'Read notes', status: 'completed', tool: 'read_file' }],
        memorySources: [{ id: 'memory-1', text: 'Prefers concise replies', layer: 'profile', source: 'conversation' }],
      }],
    })

    expect(wrapper.text()).toContain('Agent 步骤 1')
    expect(wrapper.text()).toContain('Read notes')
    expect(wrapper.text()).toContain('使用记忆 1')
    expect(wrapper.text()).toContain('Prefers concise replies')

    await wrapper.get('[data-memory-action="correct"]').trigger('click')
    await wrapper.get('[data-memory-action="forget"]').trigger('click')
    expect(wrapper.emitted('correct-memory')?.[0]).toEqual([{ id: 'memory-1', text: 'Prefers concise replies', layer: 'profile', source: 'conversation' }])
    expect(wrapper.emitted('forget-memory')?.[0]).toEqual([{ id: 'memory-1', text: 'Prefers concise replies', layer: 'profile', source: 'conversation' }])
  })
})
