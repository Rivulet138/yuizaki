import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import WorkspacePromptEditor from '../shared/components/prompt/WorkspacePromptEditor.vue'
import { DEFAULT_DAILY_PROMPT, DEFAULT_WORK_PROMPT, useWorkspaceStore } from '../stores/workspaceStore'

const waitForPromptSync = () => new Promise((resolve) => window.setTimeout(resolve, 0))

const ElementInputStub = defineComponent({
  props: {
    modelValue: {
      type: [String, Number],
      default: '',
    },
    type: {
      type: String,
      default: 'text',
    },
    placeholder: {
      type: String,
      default: '',
    },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { attrs, emit }) {
    const onInput = (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement | HTMLTextAreaElement).value)
    const onChange = (event: Event) => emit('change', (event.target as HTMLInputElement | HTMLTextAreaElement).value)
    return () => h(props.type === 'textarea' ? 'textarea' : 'input', {
      ...attrs,
      placeholder: props.placeholder,
      value: String(props.modelValue ?? ''),
      onInput,
      onChange,
    })
  },
})

const ElementSwitchStub = defineComponent({
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit }) {
    return () => h('input', {
      checked: props.modelValue,
      type: 'checkbox',
      onChange: (event: Event) => {
        const checked = (event.target as HTMLInputElement).checked
        emit('update:modelValue', checked)
        emit('change', checked)
      },
    })
  },
})

const ElementCheckboxStub = defineComponent({
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('label', [
      h('input', {
        checked: props.modelValue,
        disabled: props.disabled,
        type: 'checkbox',
        onChange: (event: Event) => {
          const checked = (event.target as HTMLInputElement).checked
          emit('update:modelValue', checked)
          emit('change', checked)
        },
      }),
      slots.default?.(),
    ])
  },
})

const global = {
  stubs: {
    'el-button': {
      props: ['disabled'],
      emits: ['click'],
      template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
    },
    'el-empty': {
      props: ['description'],
      template: '<div>{{ description }}</div>',
    },
    'el-form': { template: '<form><slot /></form>' },
    'el-form-item': {
      props: ['label'],
      template: '<label><span>{{ label }}</span><slot /></label>',
    },
    'el-checkbox': ElementCheckboxStub,
    'el-input': ElementInputStub,
    'el-input-number': ElementInputStub,
    'el-switch': ElementSwitchStub,
  },
}

describe('WorkspacePromptEditor', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('persists editable work and daily prompt engineering in the active workspace', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const promptInputs = wrapper.findAll('textarea')
    await promptInputs[0]?.setValue('自定义工作提示词')
    await promptInputs[1]?.setValue('自定义日常提示词')
    await flushPromises()

    expect(store.activeWorkspace.context.promptEngineering).toMatchObject({
      workPrompt: '自定义工作提示词',
      dailyPrompt: '自定义日常提示词',
    })

    const persisted = JSON.parse(window.localStorage.getItem('deskpet-workspaces') || '[]')
    expect(persisted[0].context.promptEngineering).toMatchObject({
      workPrompt: '自定义工作提示词',
      dailyPrompt: '自定义日常提示词',
    })
  })

  it('can reset edited base prompts back to the built-in defaults', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const promptInputs = wrapper.findAll('textarea')
    await promptInputs[0]?.setValue('自定义工作提示词')
    await promptInputs[1]?.setValue('自定义日常提示词')
    await flushPromises()

    const resetButton = wrapper.findAll('button').find((button) => button.text().includes('恢复默认'))
    expect(resetButton).toBeTruthy()
    await resetButton?.trigger('click')
    await flushPromises()

    expect(store.activeWorkspace.context.promptEngineering).toMatchObject({
      workPrompt: DEFAULT_WORK_PROMPT,
      dailyPrompt: DEFAULT_DAILY_PROMPT,
    })
  })

  it('persists role card content from JSON and allows blank input', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const roleCardInput = wrapper.findAll('textarea')[2]
    await roleCardInput?.setValue(JSON.stringify({
      data: {
        name: '結崎',
        description: '住在桌面上的本地 AI 桌宠',
        scenario: '夜间陪伴',
        first_mes: '今天也在这里。',
        system_prompt: '回答简短自然',
      },
    }, null, 2))
    await flushPromises()

    expect(store.activeWorkspace.context.roleCard).toMatchObject({
      enabled: true,
      name: '結崎',
      personality: '住在桌面上的本地 AI 桌宠',
      scenario: '夜间陪伴',
      instructions: expect.stringContaining('回答简短自然'),
      firstMessage: '今天也在这里。',
    })

    await roleCardInput?.setValue('{')
    await flushPromises()
    expect(wrapper.text()).toContain('JSON 格式不正确')
    expect(store.activeWorkspace.context.roleCard.name).toBe('結崎')

    await roleCardInput?.setValue('')
    await flushPromises()
    expect(store.activeWorkspace.context.roleCard).toMatchObject({
      enabled: true,
      name: '',
      personality: '',
      scenario: '',
      instructions: '',
      firstMessage: '',
    })
  })

  it('imports and exports role card JSON files', async () => {
    const store = useWorkspaceStore()
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:role-card')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const payload = JSON.stringify({
      name: '結崎',
      personality: '温暖、轻快',
      scenario: '夜间陪伴',
      firstMessage: '今天也在这里。',
    })
    const file = new File([payload], 'role-card.json', { type: 'application/json' })
    if (typeof file.text !== 'function') {
      Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(payload) })
    } else {
      vi.spyOn(file, 'text').mockResolvedValue(payload)
    }

    const input = wrapper.findAll('input[type="file"]')[0]
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [file],
    })
    await input.trigger('change')
    await flushPromises()

    expect(store.activeWorkspace.context.roleCard).toMatchObject({
      name: '結崎',
      personality: '温暖、轻快',
      scenario: '夜间陪伴',
      firstMessage: '今天也在这里。',
    })

    const exportButton = wrapper.findAll('button').find((button) => button.text() === '导出')
    expect(exportButton).toBeTruthy()
    await exportButton?.trigger('click')

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:role-card')
  })

  it('imports embedded character book from role card JSON without duplicating entries', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 8,
        budgetTokens: 1200,
        entries: [
          {
            id: 'existing_world_entry',
            title: '已有条目',
            keys: ['旧关键词'],
            secondaryKeys: [],
            content: '这条内容不应该被角色卡导入覆盖。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const roleCardInput = wrapper.findAll('textarea')[2]
    const roleCardPayload = {
      data: {
        name: '結崎',
        description: '住在桌面上的本地 AI 桌宠',
        first_mes: '今天也在这里。',
        system_prompt: '回答简短自然',
        character_book: {
          scan_depth: 6,
          max_entries: 4,
          token_budget: 900,
          entries: [
            {
              comment: '月见祭',
              keys: ['月见祭'],
              secondary_keys: ['秋夜'],
              content: '月见祭是你们约定过的秋夜活动。',
              selective: true,
              order: 2,
              probability: 80,
              extensions: {
                case_sensitive: true,
                match_whole_words: true,
              },
            },
          ],
        },
      },
    }
    await roleCardInput?.setValue(JSON.stringify(roleCardPayload, null, 2))
    await flushPromises()

    expect(store.activeWorkspace.context.roleCard).toMatchObject({
      name: '結崎',
      personality: '住在桌面上的本地 AI 桌宠',
      instructions: expect.stringContaining('回答简短自然'),
    })
    expect(store.activeWorkspace.context.worldBook).toMatchObject({
      enabled: true,
      scanDepth: 6,
      maxEntries: 4,
      budgetTokens: 900,
    })
    expect(store.activeWorkspace.context.worldBook.entries).toEqual([
      expect.objectContaining({
        title: '已有条目',
        content: '这条内容不应该被角色卡导入覆盖。',
      }),
      expect.objectContaining({
        title: '月见祭',
        keys: ['月见祭'],
        secondaryKeys: ['秋夜'],
        content: '月见祭是你们约定过的秋夜活动。',
        selective: true,
        insertionOrder: 2,
        probability: 80,
        caseSensitive: true,
        matchWholeWords: true,
      }),
    ])

    await roleCardInput?.setValue(`${JSON.stringify(roleCardPayload, null, 2)}\n`)
    await flushPromises()
    expect(store.activeWorkspace.context.worldBook.entries).toHaveLength(2)
  })

  it('imports tavern-style world book JSON into editable entries', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const worldBookInput = wrapper.findAll('textarea')[3]
    await worldBookInput?.setValue(JSON.stringify({
      character_book: {
        scan_depth: 6,
        token_budget: 900,
        entries: [
          {
            comment: '月见祭',
            keys: ['月见祭'],
            secondary_keys: ['秋夜'],
            content: '月见祭是你们约定过的秋夜活动。',
            selective: true,
            constant: false,
            order: 2,
            probability: 80,
            extensions: {
              case_sensitive: true,
              match_whole_words: true,
            },
          },
        ],
      },
    }))
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入 JSON'))
    expect(importButton).toBeTruthy()
    await importButton?.trigger('click')
    await flushPromises()

    expect(store.activeWorkspace.context.worldBook).toMatchObject({
      enabled: true,
      scanDepth: 6,
      budgetTokens: 900,
      entries: [
        expect.objectContaining({
          title: '月见祭',
          keys: ['月见祭'],
          secondaryKeys: ['秋夜'],
          content: '月见祭是你们约定过的秋夜活动。',
          selective: true,
          insertionOrder: 2,
          probability: 80,
          caseSensitive: true,
          matchWholeWords: true,
        }),
      ],
    })
  })

  it('can merge imported world book JSON into existing entries', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 8,
        budgetTokens: 1200,
        entries: [
          {
            id: 'existing_world_entry',
            title: '已有条目',
            keys: ['旧关键词'],
            secondaryKeys: [],
            content: '这条内容应该保留。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const worldBookInput = wrapper.findAll('textarea')[3]
    await worldBookInput?.setValue(JSON.stringify({
      entries: [
        {
          title: '新条目',
          keys: ['新关键词'],
          content: '这条内容来自追加导入。',
        },
      ],
    }))

    const mergeButton = wrapper.findAll('button').find((button) => button.text() === '追加')
    expect(mergeButton).toBeTruthy()
    await mergeButton?.trigger('click')
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入 JSON'))
    await importButton?.trigger('click')
    await flushPromises()

    expect(store.activeWorkspace.context.worldBook.entries).toEqual([
      expect.objectContaining({
        title: '已有条目',
        content: '这条内容应该保留。',
      }),
      expect.objectContaining({
        title: '新条目',
        keys: ['新关键词'],
        content: '这条内容来自追加导入。',
      }),
    ])
  })

  it('filters world book entries by title, keys, and content', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 8,
        budgetTokens: 1200,
        entries: [
          {
            id: 'world_moon',
            title: '月见祭',
            keys: ['月见祭'],
            secondaryKeys: [],
            content: '秋夜活动。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_port',
            title: '星屑港',
            keys: ['港口'],
            secondaryKeys: [],
            content: '安全地点。',
            enabled: true,
            priority: 0,
            insertionOrder: 1,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const filterInput = wrapper.find('input[placeholder="筛选条目"]')
    await filterInput.setValue('月见')
    await flushPromises()

    expect(wrapper.findAll('.world-entry')).toHaveLength(1)
    expect((wrapper.find('.world-entry input[placeholder="条目名称"]').element as HTMLInputElement).value).toBe('月见祭')
    expect(wrapper.text()).toContain('1 / 2')
  })

  it('can select filtered world book entries and delete only the selected rows', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 8,
        budgetTokens: 1200,
        entries: [
          {
            id: 'world_moon',
            title: '月见祭',
            keys: ['月见祭'],
            secondaryKeys: [],
            content: '秋夜活动。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_port',
            title: '星屑港',
            keys: ['港口'],
            secondaryKeys: [],
            content: '安全地点。',
            enabled: true,
            priority: 0,
            insertionOrder: 1,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    await wrapper.find('input[placeholder="筛选条目"]').setValue('月见')
    await flushPromises()

    const selectFilteredInput = wrapper.findAll('label')
      .find((label) => label.text().includes('选中结果'))
      ?.find('input')
    expect(selectFilteredInput).toBeTruthy()
    await selectFilteredInput?.setValue(true)
    await flushPromises()

    const deleteButton = wrapper.findAll('button').find((button) => button.text().includes('删除选中'))
    expect(deleteButton).toBeTruthy()
    await deleteButton?.trigger('click')
    await flushPromises()

    expect(store.activeWorkspace.context.worldBook.entries).toEqual([
      expect.objectContaining({
        id: 'world_port',
        title: '星屑港',
      }),
    ])
  })

  it('imports world book entries from a JSON file', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const payload = JSON.stringify({
      entries: [
        {
          name: '星屑港',
          key: ['星屑港'],
          content: '星屑港是桌宠常提起的安全地点。',
          constant: true,
        },
      ],
    })
    const file = new File([payload], 'world-book.json', { type: 'application/json' })
    if (typeof file.text !== 'function') {
      Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(payload) })
    } else {
      vi.spyOn(file, 'text').mockResolvedValue(payload)
    }

    const input = wrapper.findAll('input[type="file"]')[1]
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [file],
    })
    await input.trigger('change')
    await flushPromises()

    expect(store.activeWorkspace.context.worldBook.entries).toEqual([
      expect.objectContaining({
        title: '星屑港',
        keys: ['星屑港'],
        content: '星屑港是桌宠常提起的安全地点。',
        constant: true,
      }),
    ])
  })

  it('imports common lorebook item maps and keeps large lists paged', async () => {
    const store = useWorkspaceStore()
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const worldBookInput = wrapper.findAll('textarea')[3]
    const entries = Object.fromEntries(Array.from({ length: 45 }, (_, index) => [
      `entry_${index}`,
      {
        uid: index,
        memo: `条目 ${index + 1}`,
        key: [`关键词 ${index + 1}`],
        entry: `内容 ${index + 1}`,
      },
    ]))

    await worldBookInput?.setValue(JSON.stringify({ items: entries }))
    const importButton = wrapper.findAll('button').find((button) => button.text().includes('导入 JSON'))
    await importButton?.trigger('click')
    await flushPromises()

    expect(store.activeWorkspace.context.worldBook.entries).toHaveLength(45)
    expect(store.activeWorkspace.context.worldBook.entries[0]).toEqual(expect.objectContaining({
      id: '0',
      title: '条目 1',
      keys: ['关键词 1'],
      content: '内容 1',
    }))
    expect(wrapper.findAll('.world-entry')).toHaveLength(40)
    expect(wrapper.text()).toContain('第 1 / 2 页')

    const nextButton = wrapper.findAll('button').find((button) => button.text().includes('下一页'))
    await nextButton?.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.world-entry')).toHaveLength(5)
    expect(wrapper.text()).toContain('第 2 / 2 页')
  })

  it('previews world book matches with constant and selective entries', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 2,
        maxEntries: 4,
        budgetTokens: 1200,
        entries: [
          {
            id: 'world_constant',
            title: '常驻设定',
            keys: [],
            secondaryKeys: [],
            content: '桌宠会记得当前用户偏好。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: true,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_moon',
            title: '月见祭',
            keys: ['月见祭'],
            secondaryKeys: ['秋夜'],
            content: '月见祭是你们约定过的秋夜活动。',
            enabled: true,
            priority: 5,
            insertionOrder: 1,
            constant: false,
            selective: true,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_missing_secondary',
            title: '缺少二级',
            keys: ['月见祭'],
            secondaryKeys: ['晴天'],
            content: '这条需要二级关键词。',
            enabled: true,
            priority: 4,
            insertionOrder: 2,
            constant: false,
            selective: true,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_disabled',
            title: '已停用',
            keys: ['秋夜'],
            secondaryKeys: [],
            content: '这条已经停用。',
            enabled: false,
            priority: 9,
            insertionOrder: 3,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
          {
            id: 'world_zero_probability',
            title: '零概率',
            keys: ['秋夜'],
            secondaryKeys: [],
            content: '这条概率为零。',
            enabled: true,
            priority: 8,
            insertionOrder: 4,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 0,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    expect(wrapper.find('[data-testid="world-book-preview"]').text()).toContain('常驻设定')
    expect(wrapper.find('[data-testid="world-book-preview"]').text()).toContain('命中 1 条')

    await wrapper.find('[data-testid="world-book-preview-input"]').setValue('前面的话不会参与扫描\n聊到了月见祭\n今晚是秋夜')
    await flushPromises()

    const previewText = wrapper.find('[data-testid="world-book-preview"]').text()
    expect(previewText).toContain('命中 2 条')
    expect(previewText).toContain('月见祭')
    expect(previewText).toContain('常驻设定')
    expect(previewText).not.toContain('缺少二级')
    expect(previewText).not.toContain('已停用')
    expect(previewText).not.toContain('零概率')

    await wrapper.find('.world-preview-item').trigger('click')
    await flushPromises()
    expect((wrapper.find('input[placeholder="筛选条目"]').element as HTMLInputElement).value).toBe('月见祭')
  })

  it('previews world book matches with whole-word case checks and max entry limit', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 1,
        budgetTokens: 1200,
        entries: [
          {
            id: 'world_api',
            title: 'API 整词',
            keys: ['API'],
            secondaryKeys: [],
            content: '只在大写 API 单独出现时插入。',
            enabled: true,
            priority: 5,
            insertionOrder: 0,
            constant: false,
            selective: false,
            caseSensitive: true,
            matchWholeWords: true,
            probability: 100,
          },
          {
            id: 'world_beta',
            title: '低优先级',
            keys: ['beta'],
            secondaryKeys: [],
            content: '低优先级内容。',
            enabled: true,
            priority: 1,
            insertionOrder: 1,
            constant: false,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const previewInput = wrapper.find('[data-testid="world-book-preview-input"]')
    await previewInput.setValue('api APIs beta')
    await flushPromises()

    expect(wrapper.find('[data-testid="world-book-preview"]').text()).toContain('低优先级')
    expect(wrapper.find('[data-testid="world-book-preview"]').text()).not.toContain('API 整词')

    await previewInput.setValue('调用 API，同时也提到 beta')
    await flushPromises()

    const previewText = wrapper.find('[data-testid="world-book-preview"]').text()
    expect(previewText).toContain('命中 1 条')
    expect(previewText).toContain('API 整词')
    expect(previewText).not.toContain('低优先级')
  })

  it('exports the current world book as a JSON file', async () => {
    const store = useWorkspaceStore()
    store.updateWorkspaceContext(store.activeWorkspaceId, {
      worldBook: {
        enabled: true,
        scanDepth: 8,
        maxEntries: 8,
        budgetTokens: 1200,
        entries: [
          {
            id: 'world_stardust_port',
            title: '星屑港',
            keys: ['星屑港'],
            secondaryKeys: [],
            content: '星屑港是桌宠常提起的安全地点。',
            enabled: true,
            priority: 0,
            insertionOrder: 0,
            constant: true,
            selective: false,
            caseSensitive: false,
            matchWholeWords: false,
            probability: 100,
          },
        ],
      },
    })
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:world-book')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const wrapper = mount(WorkspacePromptEditor, { global })
    await waitForPromptSync()

    const exportButton = wrapper.findAll('button').find((button) => button.text().includes('导出文件'))
    expect(exportButton).toBeTruthy()
    await exportButton?.trigger('click')

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:world-book')
  })
})
